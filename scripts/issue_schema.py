#!/usr/bin/env python3
"""Server-side enforcement of the repository's GitHub Issue Form schema.

GitHub Issue Form templates (``.github/ISSUE_TEMPLATE/*.yml``) only enforce
their required-field schema through the web UI. Issues created via the REST API
or any external client bypass that check entirely. This module restores the
contract server-side: it derives the required section headers from the form
template, validates that an issue body contains each required ``### <Label>``
header with non-empty content, and emits a JSON report plus a preformatted
rejection comment for the companion workflow to post.

Zero external dependencies (stdlib only) so it runs offline in any CI runner,
matching the philosophy documented in ``scripts/secret_scan.py``.

Trigger invariant (enforced by the companion workflow
``.github/workflows/issue-schema-enforcement.yml``):
    The workflow NEVER edits an issue's body or title. Commenting, labeling,
    and closing fire ``issue_comment``, ``labeled``, and ``closed`` events —
    none of which the workflow listens to — so it cannot re-trigger itself
    (no infinite loop on issue edits). The invariant is the root-cause
    prevention; no actor filters are used, since those risk false negatives on
    legitimate API-filed issues (e.g. the autonomous planner).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

HEADER_RE = re.compile(r"^###\s+(.+?)\s*$")


@dataclass
class ValidationResult:
    """Outcome of validating an issue body against the required headers."""

    missing: list[str] = field(default_factory=list)
    empty: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.missing and not self.empty


def _unquote(value: str) -> str:
    """Strip a single pair of surrounding quotes from a YAML scalar value."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def parse_issue_form_template(template_path: Path) -> list[tuple[str, bool]]:
    """Parse a GitHub Issue Form template into ``(label, required)`` pairs.

    This is a minimal, dependency-free parser for the regular subset of YAML
    GitHub uses for issue forms. A field contributes a pair only when it
    declares a ``label:`` (so ``type: markdown`` intro blocks are skipped).
    Required-ness is read from the ``validations.required`` flag.
    """
    fields: list[tuple[str, bool]] = []
    label: str | None = None
    required = False
    in_validations = False

    for raw in template_path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()

        # A new list item starts a new field block.
        if stripped.startswith("- type:"):
            if label is not None:
                fields.append((label, required))
            label = None
            required = False
            in_validations = False
            continue

        if stripped == "attributes:":
            in_validations = False
            continue
        if stripped == "validations:":
            in_validations = True
            continue

        if stripped.startswith("label:") and not in_validations:
            label = _unquote(stripped[len("label:") :].strip())
            continue
        if stripped.startswith("required:") and in_validations:
            required = stripped[len("required:") :].strip().lower() == "true"
            continue

    if label is not None:
        fields.append((label, required))
    return fields


def required_headers(fields: list[tuple[str, bool]]) -> list[str]:
    """Return the labels of fields marked as required, in declaration order."""
    return [label for label, req in fields if req]


def _sections(body: str) -> dict[str, str]:
    """Map each ``### <Header>`` to its section content (up to the next header).

    Only H3 (``###``) headers are recognized — that is what GitHub Issue Forms
    render for each form field. H2/H4 and the intro markdown block are ignored.
    """
    sections: dict[str, str] = {}
    current_header: str | None = None
    current_lines: list[str] = []

    for raw in body.splitlines():
        match = HEADER_RE.match(raw)
        if match:
            if current_header is not None:
                sections[current_header] = "\n".join(current_lines)
            current_header = match.group(1)
            current_lines = []
        elif current_header is not None:
            current_lines.append(raw)

    if current_header is not None:
        sections[current_header] = "\n".join(current_lines)
    return sections


def validate_issue_body(body: str, required: list[str]) -> ValidationResult:
    """Validate that ``body`` contains every required header with content.

    A required field is satisfied iff a ``### <Label>`` line exists for it AND
    the section content (until the next ``###`` header or end of body) contains
    non-whitespace text. The label is matched exactly as written in the template
    (case-sensitive), which is the schema the form renders.
    """
    sections = _sections(body) if body else {}
    missing = [h for h in required if h not in sections]
    empty = [h for h in required if h in sections and not sections[h].strip()]
    return ValidationResult(missing=missing, empty=empty)


def build_rejection_comment(missing: list[str], empty: list[str]) -> str:
    """Render the markdown comment posted on a non-compliant issue."""
    lines: list[str] = [
        "## ⚠️ Issue closed: does not follow the required schema",
        "",
        "This issue was automatically closed because it does not conform to the "
        "repository's `Task` issue template "
        "(`.github/ISSUE_TEMPLATE/task.yml`).",
        "",
    ]
    if missing:
        lines.append("**Missing required sections:**")
        for header in missing:
            lines.append(f"- `### {header}`")
        lines.append("")
    if empty:
        lines.append("**Required sections present but empty:**")
        for header in empty:
            lines.append(f"- `### {header}`")
        lines.append("")
    lines.extend(
        [
            "Each required section must be present as a `### <Section>` heading "
            "and contain non-empty content.",
            "",
            "To reopen this issue, edit its body to include all required "
            "sections and submit. The schema check runs automatically on edit.",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--template", required=True, help="path to the issue form template YAML"
    )
    parser.add_argument(
        "--body-file", required=True, help="path to a file holding the issue body"
    )
    parser.add_argument(
        "--comment-file",
        help="path to write the preformatted rejection comment markdown to "
        "(only written when the issue is non-compliant)",
    )
    args = parser.parse_args()

    body = Path(args.body_file).read_text(encoding="utf-8")
    fields = parse_issue_form_template(Path(args.template))
    required = required_headers(fields)
    result = validate_issue_body(body, required)

    report = {
        "valid": result.is_valid,
        "missing": result.missing,
        "empty": result.empty,
        "required_headers": required,
    }
    print(json.dumps(report, indent=2))

    if not result.is_valid and args.comment_file:
        Path(args.comment_file).write_text(
            build_rejection_comment(result.missing, result.empty), encoding="utf-8"
        )

    return 0 if result.is_valid else 1


if __name__ == "__main__":
    sys.exit(main())
