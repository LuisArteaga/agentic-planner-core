"""Tests for the server-side issue schema validator (scripts/issue_schema.py)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# Ensure project root is in sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from scripts.issue_schema import (  # noqa: E402
    build_rejection_comment,
    parse_issue_form_template,
    required_headers,
    validate_issue_body,
)

REPO_ROOT = Path(project_root)
TEMPLATE = REPO_ROOT / ".github" / "ISSUE_TEMPLATE" / "task.yml"
SCRIPT = REPO_ROOT / "scripts" / "issue_schema.py"

# The required headers the committed template declares. This is also a drift
# guard: if task.yml changes its required fields, this test fails loudly so the
# enforcement policy stays in sync with the template.
EXPECTED_REQUIRED = [
    "What to build",
    "Scope",
    "Constraints",
    "Edge cases",
    "Cross-cutting concerns",
    "Acceptance criteria",
]

VALID_BODY = """\
### What to build

Implement the thing.

### Scope

ci

### Constraints

- Must be native GitHub Actions.

### Edge cases

Empty bodies.

### Cross-cutting concerns

DX.

### Acceptance criteria

- [ ] Workflow validates headers
- [ ] Auto-close and label invalid
- [ ] Document the setup

### Blocked by

none
"""


def test_parse_template_extracts_required_headers() -> None:
    fields = parse_issue_form_template(TEMPLATE)
    assert required_headers(fields) == EXPECTED_REQUIRED


def test_parse_template_marks_optional_field_not_required() -> None:
    fields = dict(parse_issue_form_template(TEMPLATE))
    assert fields.get("Blocked by") is False


def test_validate_valid_body() -> None:
    result = validate_issue_body(VALID_BODY, EXPECTED_REQUIRED)
    assert result.is_valid
    assert result.missing == []
    assert result.empty == []


def test_validate_missing_header() -> None:
    body = VALID_BODY.replace("### Scope\n\nci\n\n", "")
    result = validate_issue_body(body, EXPECTED_REQUIRED)
    assert not result.is_valid
    assert result.missing == ["Scope"]
    assert result.empty == []


def test_validate_empty_section() -> None:
    body = VALID_BODY.replace("ci", "")
    result = validate_issue_body(body, EXPECTED_REQUIRED)
    assert not result.is_valid
    assert result.empty == ["Scope"]
    assert result.missing == []


def test_validate_completely_empty_body() -> None:
    result = validate_issue_body("", EXPECTED_REQUIRED)
    assert not result.is_valid
    assert result.missing == EXPECTED_REQUIRED
    assert result.empty == []


def test_validate_optional_field_absence_is_valid() -> None:
    body = VALID_BODY.replace("### Blocked by\n\nnone\n", "")
    result = validate_issue_body(body, EXPECTED_REQUIRED)
    assert result.is_valid


def test_validate_header_with_trailing_whitespace_is_matched() -> None:
    body = VALID_BODY.replace("### Scope\n", "### Scope   \n")
    result = validate_issue_body(body, EXPECTED_REQUIRED)
    assert result.is_valid


def test_validate_ignores_intro_markdown_block() -> None:
    # GitHub may prepend a type:markdown intro block (with its own ### heading)
    # to the submitted body; it must not be confused with a required section.
    body = "### Task-Spezifikation für den Agenten\n\nIntro text.\n\n" + VALID_BODY
    result = validate_issue_body(body, EXPECTED_REQUIRED)
    assert result.is_valid


def test_build_rejection_comment_lists_missing_and_empty() -> None:
    comment = build_rejection_comment(missing=["Scope"], empty=["Constraints"])
    assert "Missing required sections" in comment
    assert "`### Scope`" in comment
    assert "Required sections present but empty" in comment
    assert "`### Constraints`" in comment
    assert "edit its body" in comment


def test_cli_returns_zero_for_valid_body(tmp_path: Path) -> None:
    body = tmp_path / "body.md"
    body.write_text(VALID_BODY, encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--template",
            str(TEMPLATE),
            "--body-file",
            str(body),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert '"valid": true' in proc.stdout


def test_cli_returns_one_and_writes_comment_for_invalid_body(tmp_path: Path) -> None:
    body = tmp_path / "body.md"
    body.write_text("### Scope\n\nci\n", encoding="utf-8")
    comment = tmp_path / "comment.md"
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--template",
            str(TEMPLATE),
            "--body-file",
            str(body),
            "--comment-file",
            str(comment),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert '"valid": false' in proc.stdout
    assert comment.exists()
    assert "Missing required sections" in comment.read_text(encoding="utf-8")
