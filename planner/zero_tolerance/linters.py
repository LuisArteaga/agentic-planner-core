"""Deterministic core lints for the Zero-Error-Tolerance AddOn.

No LLM calls: these checks are fully deterministic to avoid LLM-drift
inconsistencies (AddOn constraint). They parse draft-issue markdown, the domain
glossary (``CONTEXT.md``), and ADR directories directly.

Dependency cycle detection uses Python's standard ``graphlib.TopologicalSorter``
(Kahn's algorithm): a graph has a valid topological ordering iff it is a DAG, so
topological-sort failure doubles as cycle detection.
"""

import graphlib
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from planner.zero_tolerance.models import (
    GlossaryEntry,
    LintFinding,
    Severity,
    ZeroToleranceConfig,
)

# Matches a level-3 glossary heading, e.g. "### Entwurfs-Aufgabe (Draft Issue)".
_GLOSSARY_HEADING_RE = re.compile(r"^###\s+(.+?)\s*$")
# Matches an ADR/AgDR reference: "ADR-0001", "AgDR-0012", or a markdown link to
# docs/adr/0001-...md / docs/agdr/0012-...md.
_ADR_REF_RE = re.compile(r"(?:Ag?DR[-\s]?(\d{1,4})|docs/ag?dr/(\d{1,4})[-\w]*\.md)")
# Matches the 4-digit prefix of a draft filename, e.g. "0003" in
# "0003-implement-auth.md".
_FILENAME_NUM_RE = re.compile(r"^(\d{4})")


def _split_canonical_terms(heading: str) -> List[str]:
    """Split a glossary heading into lowercase canonical term forms.

    A heading like ``Entwurfs-Aufgabe (Draft Issue)`` yields
    ``["entwurfs-aufgabe", "draft issue"]``. Parentheticals, surrounding
    markdown emphasis, and trailing qualifiers are stripped.
    """
    # Strip markdown emphasis and whitespace.
    cleaned = re.sub(r"[*_`]", "", heading).strip()
    # Split off parenthetical alternatives, e.g. "Term (Alt Form)".
    parts = re.split(r"[()]", cleaned)
    terms: List[str] = []
    for part in parts:
        term = part.strip().strip("-–—:").strip()
        if term:
            terms.append(term.lower())
    return terms


def parse_glossary(context_path: str) -> Dict[str, GlossaryEntry]:
    """Parse a ``CONTEXT.md`` glossary into a mapping of canonical-term -> entry.

    The key is the first canonical term (lowercase). Deprecated synonyms are
    extracted from a ``Veraltete Synonyme:`` prefix in the
    "Synonyme / Abzugrenzende Begriffe" field, e.g.::

        ### Customer
        * **Synonyme / Abzugrenzende Begriffe**: Veraltete Synonyme: Client

    Returns an empty dict if the file is missing or has no term headings.
    """
    path = Path(context_path)
    if not path.exists():
        return {}

    text = path.read_text(encoding="utf-8")
    entries: Dict[str, GlossaryEntry] = {}
    current_terms: Optional[List[str]] = None

    for line in text.splitlines():
        heading_match = _GLOSSARY_HEADING_RE.match(line)
        if heading_match:
            current_terms = _split_canonical_terms(heading_match.group(1))
            continue
        if current_terms and "Synonyme" in line and "Abzugrenzende" in line:
            # Extract deprecated synonyms after an explicit "Veraltete Synonyme:" marker.
            dep: List[str] = []
            if "Veraltete Synonyme:" in line:
                after = line.split("Veraltete Synonyme:", 1)[1]
                # Take everything after the marker up to the end of the field value.
                value = after.split("\n")[0]
                value = re.sub(r"[*_`]", "", value).strip()
                # Stop at a sentence boundary if the field continues narratively.
                value = re.split(r"[.;]", value)[0]
                # Preserve original case for readable lint messages; matching is
                # case-insensitive in glossary_lint.
                dep = [s.strip() for s in value.split(",") if s.strip()]
            key = current_terms[0]
            entries[key] = GlossaryEntry(
                canonical_terms=current_terms, deprecated_synonyms=dep
            )
            current_terms = None

    return entries


def parse_blocked_by(content: str) -> List[str]:
    """Extract blocker filenames from a draft issue's ``## Blocked by`` section.

    Returns the raw referenced filenames (e.g. ``0001-setup-schema.md``) or
    ``["None"]`` normalised to an empty list. Blocker references are split on
    commas and newlines.
    """
    lines = content.splitlines()
    in_section = False
    blockers: List[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            in_section = stripped.lower().startswith("## blocked by")
            continue
        if in_section:
            if not stripped:
                continue
            for token in re.split(r"[,\n]", stripped):
                token = token.strip().lstrip("-*").strip()
                if token and token.lower() != "none":
                    blockers.append(token)
    return blockers


def parse_scope(content: str) -> str:
    """Extract the single-word scope value from the ``## Scope`` section."""
    lines = content.splitlines()
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            in_section = stripped.lower().startswith("## scope")
            continue
        if in_section and stripped:
            return stripped.lower()
    return ""


def _whole_word_present(haystack_lower: str, needle_lower: str) -> bool:
    """Case-insensitive whole-word match (word boundaries = non-alphanumeric)."""
    pattern = r"(?<![A-Za-z0-9])" + re.escape(needle_lower) + r"(?![A-Za-z0-9])"
    return re.search(pattern, haystack_lower) is not None


def glossary_lint(
    draft_contents: Dict[str, str], glossary: Dict[str, GlossaryEntry]
) -> List[LintFinding]:
    """Flag draft issues that use a deprecated synonym without the canonical term.

    For each glossary entry that declares deprecated synonyms, if a draft issue
    contains a deprecated synonym (whole-word, case-insensitive) but none of the
    canonical terms, the draft is flagged with an ERROR.
    """
    findings: List[LintFinding] = []
    for issue_name, content in draft_contents.items():
        content_lower = content.lower()
        for entry in glossary.values():
            if not entry.deprecated_synonyms:
                continue
            canonical_present = any(
                _whole_word_present(content_lower, t) for t in entry.canonical_terms
            )
            if canonical_present:
                continue
            for syn in entry.deprecated_synonyms:
                if _whole_word_present(content_lower, syn.lower()):
                    canonical = (
                        entry.canonical_terms[0] if entry.canonical_terms else "?"
                    )
                    findings.append(
                        LintFinding(
                            check="glossary",
                            severity=Severity.ERROR,
                            issue=issue_name,
                            message=(
                                f"Issue uses '{syn}' instead of '{canonical}' "
                                f"(Glossary violation)."
                            ),
                        )
                    )
    return findings


def dependency_lint(
    draft_contents: Dict[str, str],
) -> Tuple[List[LintFinding], Dict[str, List[str]]]:
    """Validate the draft-issue dependency DAG.

    Returns the findings and the parsed dependency map (filename -> blockers).
    Detects:
      * dangling references (a blocker filename that is not a known draft), and
      * cycles (via ``graphlib.TopologicalSorter``, which raises ``CycleError``).
    """
    findings: List[LintFinding] = []
    dep_map: Dict[str, List[str]] = {}
    for issue_name, content in draft_contents.items():
        dep_map[issue_name] = parse_blocked_by(content)

    known = set(draft_contents.keys())
    # Dangling references.
    for issue_name, blockers in dep_map.items():
        for blocker in blockers:
            if blocker not in known:
                findings.append(
                    LintFinding(
                        check="dependency",
                        severity=Severity.ERROR,
                        issue=issue_name,
                        message=(
                            f"Blocked-by reference '{blocker}' does not match any "
                            f"known draft issue file."
                        ),
                    )
                )

    # Cycle detection via Kahn's algorithm (graphlib.TopologicalSorter).
    # Only consider edges to known drafts for the graph.
    graph: Dict[str, Set[str]] = {name: set() for name in known}
    for issue_name, blockers in dep_map.items():
        for blocker in blockers:
            if blocker in known:
                # blocker must come before issue_name: edge blocker -> issue_name.
                graph.setdefault(blocker, set()).add(issue_name)
    try:
        ts = graphlib.TopologicalSorter(graph)
        # static_order() raises CycleError if the graph contains a cycle.
        list(ts.static_order())
    except graphlib.CycleError as exc:
        cycle_desc = (
            ", ".join(str(n) for n in exc.args[1]) if len(exc.args) > 1 else "cycle"
        )
        findings.append(
            LintFinding(
                check="dependency",
                severity=Severity.ERROR,
                issue="(graph)",
                message=f"Circular dependency detected in draft-issue DAG: {cycle_desc}.",
            )
        )

    return findings, dep_map


def _collect_existing_adr_numbers(adr_dirs: List[str]) -> Set[str]:
    """Collect the set of 4-digit ADR/AgDR numbers that exist on disk."""
    numbers: Set[str] = set()
    for adr_dir in adr_dirs:
        dir_path = Path(adr_dir)
        if not dir_path.exists():
            continue
        for f in dir_path.glob("*.md"):
            m = _FILENAME_NUM_RE.match(f.name)
            if m:
                numbers.add(m.group(1))
    return numbers


def adr_traceability_lint(
    draft_contents: Dict[str, str], adr_dirs: List[str]
) -> List[LintFinding]:
    """Flag draft issues that reference an ADR/AgDR number with no matching file."""
    existing = _collect_existing_adr_numbers(adr_dirs)
    findings: List[LintFinding] = []
    for issue_name, content in draft_contents.items():
        referenced: Set[str] = set()
        for m in _ADR_REF_RE.finditer(content):
            num = m.group(1) or m.group(2)
            if num:
                referenced.add(num.zfill(4))
        for num in sorted(referenced):
            if num not in existing:
                findings.append(
                    LintFinding(
                        check="adr_traceability",
                        severity=Severity.ERROR,
                        issue=issue_name,
                        message=(
                            f"References ADR/AgDR '{num}' but no matching "
                            f"decision record file was found in {adr_dirs}."
                        ),
                    )
                )
    return findings


def structural_signature(content: str) -> str:
    """Compute a deterministic structural signature of a draft issue.

    Captures the section headings, the scope, and the sorted ``Blocked by``
    targets — the aspects whose change should invalidate downstream issues per
    the cascade collision gate. Content wording is intentionally excluded so
    that enrichment (which rewrites prose) is NOT treated as structural.
    """
    headings = tuple(
        line.strip() for line in content.splitlines() if line.strip().startswith("## ")
    )
    scope = parse_scope(content)
    blockers = tuple(sorted(parse_blocked_by(content)))
    return f"headings={headings}|scope={scope}|blocked_by={blockers}"


def is_trivial(content: str, config: ZeroToleranceConfig) -> bool:
    """Triviality gate: bypass LLM validation for trivial draft issues.

    A draft is trivial when it is small (few non-empty lines), declares no
    blockers, references no ADRs, and its scope is in the configured trivial
    scopes (default: ``docs``). Adapted from the Fable Method's trivial fast-path
    (1 file, <10 lines, no searching).
    """
    non_empty_lines = sum(1 for line in content.splitlines() if line.strip())
    if non_empty_lines > config.trivial_max_lines:
        return False
    if parse_blocked_by(content):
        return False
    if _ADR_REF_RE.search(content):
        return False
    scope = parse_scope(content)
    if scope not in config.trivial_scopes:
        return False
    return True


def reverse_dependency_map(dep_map: Dict[str, List[str]]) -> Dict[str, List[str]]:
    """Invert a dependency map into filename -> dependents (downstream issues)."""
    reverse: Dict[str, List[str]] = {name: [] for name in dep_map}
    for issue_name, blockers in dep_map.items():
        for blocker in blockers:
            reverse.setdefault(blocker, []).append(issue_name)
    return reverse
