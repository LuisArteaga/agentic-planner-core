"""Docs-drift guard for docs/architecture.md (issue #73).

Asserts the end-to-end architecture reference exists and still documents the
canonical CLI commands/flags, the safety gates, and the key ADR references.
If a CLI flag or gate is renamed/removed without updating the doc, this test
fails loudly — the same contract-guard pattern used by
``tests/test_issue_schema.py``.
"""

from pathlib import Path

import pytest

ARCH_DOC = Path(__file__).resolve().parents[1] / "docs" / "architecture.md"


@pytest.fixture(scope="module")
def arch_text() -> str:
    """Load the architecture doc once for the whole module.

    Existence is asserted by ``test_architecture_doc_file_exists`` so a missing
    file surfaces as a clear failure rather than an opaque fixture error.
    """
    return ARCH_DOC.read_text(encoding="utf-8")


def test_architecture_doc_file_exists() -> None:
    assert ARCH_DOC.exists(), f"Missing end-to-end architecture doc: {ARCH_DOC}"


def test_architecture_doc_has_title(arch_text: str) -> None:
    assert "# How agentic-planner-core Works" in arch_text


@pytest.mark.parametrize(
    "command",
    [
        "python -m planner grill",
        "python -m planner verify",
        "python -m planner draft",
        "python -m planner refine",
        "python -m planner eval",
    ],
)
def test_architecture_doc_lists_every_cli_command(arch_text: str, command: str) -> None:
    assert command in arch_text, f"CLI command '{command}' not documented"


@pytest.mark.parametrize(
    "flag",
    ["--config", "--zero-tolerance", "--interactive", "--yes", "--judge"],
)
def test_architecture_doc_lists_every_refine_eval_flag(
    arch_text: str, flag: str
) -> None:
    assert flag in arch_text, f"CLI flag '{flag}' not documented"


def test_architecture_doc_documents_hitl_publish_gate(arch_text: str) -> None:
    assert "## The HITL Publish Gate" in arch_text
    # The three controlling signals must all be mentioned.
    for signal in ["require_approval", "--interactive", "--yes"]:
        assert signal in arch_text


def test_architecture_doc_documents_refinement_subgraph(arch_text: str) -> None:
    # Every refinement node must appear in the doc.
    for node in [
        "analyze_sources",
        "web_search",
        "propose_options",
        "evaluate_grade",
        "security_audit",
        "apply_decision",
        "detect_structural_change",
        "threshold_check",
        "intent_gate",
        "planning_judge",
        "publish_issue",
    ]:
        assert node in arch_text, f"Refinement node '{node}' not documented"
    # A mermaid diagram must be present.
    assert "```mermaid" in arch_text


def test_architecture_doc_references_key_adrs(arch_text: str) -> None:
    for adr in ["0001", "0002", "0005", "0019", "0020", "0021"]:
        assert adr in arch_text, f"ADR {adr} not referenced"


def test_architecture_doc_documents_safety_gates(arch_text: str) -> None:
    assert "## Safety & Quality Gates" in arch_text
    for gate in [
        "Strict source allowlist",
        "GitHub API quota check",
        "Zero-Error-Tolerance batch gate",
        "Per-draft wall-clock budget",
        "LLM-Judge PR review",
    ]:
        assert gate in arch_text, f"Safety gate '{gate}' not documented"
