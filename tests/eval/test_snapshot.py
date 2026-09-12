"""Tests for the judge-artifact snapshot module (ADR-0022).

Behavioral tests against the public surface only: the parser
(``evaluate_response``), the architecture-context loader
(``load_architecture_context``), and the prompt identity contract between
the snapshot and the eval judge adapter. The ``parse_xml_tags`` helper is
exercised through ``evaluate_response`` inputs (missing/unclosed tags),
never patched or imported for direct structural assertions.
"""

import json
import os

from planner.eval.snapshot import (
    SYSTEM_PROMPT_ARCH,
    SYSTEM_PROMPT_SECURITY,
    SYSTEM_PROMPT_SYNTAX_LINT,
    SYSTEM_PROMPT_TEST_COVERAGE,
    evaluate_response,
    load_architecture_context,
)


def response_with(content):
    """Wrap judge content into the OpenRouter envelope the parser reads."""
    return json.dumps({"choices": [{"message": {"content": content}}]})


# --------------------------- evaluate_response ------------------------------


def test_evaluate_response_pass_on_empty_findings():
    raw = response_with("<reasoning>all good</reasoning>\n<findings></findings>")
    verdict, reasoning, findings = evaluate_response(raw)
    assert verdict == "Pass"
    assert reasoning == "all good"
    assert findings == []


def test_evaluate_response_fail_parses_single_finding():
    content = (
        "<reasoning>bad naming</reasoning>\n"
        '<findings>{"severity": "error", "message": "[Q3] missing prefix"}</findings>'
    )
    verdict, reasoning, findings = evaluate_response(response_with(content))
    assert verdict == "Fail"
    assert reasoning == "bad naming"
    assert findings == ["error|[Q3] missing prefix"]


def test_evaluate_response_multiple_findings_flip_verdict():
    content = (
        "<reasoning>two issues</reasoning>\n"
        "<findings>\n"
        '{"severity": "error", "message": "[Q1] syntax"}\n'
        '{"severity": "security", "message": "[Q2] injection"}\n'
        "</findings>"
    )
    verdict, _, findings = evaluate_response(response_with(content))
    assert verdict == "Fail"
    assert len(findings) == 2


def test_evaluate_response_empty_content_needs_review():
    verdict, reasoning, findings = evaluate_response(response_with(""))
    assert verdict == "Needs Review"
    assert reasoning == "Empty response from LLM"
    assert findings == []


def test_evaluate_response_missing_tags_needs_review():
    verdict, reasoning, findings = evaluate_response(
        response_with("Refusal: I cannot review this diff.")
    )
    assert verdict == "Needs Review"
    assert "lacks both <reasoning> and <findings> tags" in reasoning
    assert "Refusal: I cannot review this diff." in reasoning
    assert findings == []


def test_evaluate_response_unclosed_findings_block_is_tolerated():
    # Missing </findings> close tag: the parser returns the trailing block.
    content = (
        "<reasoning>partial</reasoning>\n"
        '<findings>{"severity": "error", "message": "[Q1] typo"}'
    )
    verdict, _, findings = evaluate_response(response_with(content))
    assert verdict == "Fail"
    assert findings == ["error|[Q1] typo"]


def test_evaluate_response_skips_blank_lines_in_findings():
    # parse_xml_tags strips the block edges, so the blank line must sit
    # between findings to exercise the empty-line skip.
    content = (
        "<reasoning>blank lines</reasoning>\n"
        '<findings>{"severity": "error", "message": "[Q1] real"}\n'
        "\n"
        '{"severity": "error", "message": "[Q2] also real"}</findings>'
    )
    verdict, _, findings = evaluate_response(response_with(content))
    assert verdict == "Fail"
    assert findings == ["error|[Q1] real", "error|[Q2] also real"]


def test_evaluate_response_skips_non_dict_finding_lines():
    content = (
        "<reasoning>mixed</reasoning>\n"
        "<findings>\n"
        '["not", "a", "dict"]\n'
        "not json at all\n"
        '{"severity": "error", "message": "[Q2] real finding"}\n'
        "</findings>"
    )
    verdict, _, findings = evaluate_response(response_with(content))
    assert verdict == "Fail"
    assert findings == ["error|[Q2] real finding"]


def test_evaluate_response_defaults_severity_and_flattens_message():
    content = (
        "<reasoning>no severity key</reasoning>\n"
        '<findings>{"message": "line one\\nline two"}</findings>'
    )
    verdict, _, findings = evaluate_response(response_with(content))
    assert verdict == "Fail"
    assert findings == ["bug|line one line two"]


# --------------------- load_architecture_context ----------------------------


def make_workspace(tmp_path, context_name="CONTEXT.md", flat_adr=False):
    """Create a workspace with a context file and one ADR each."""
    if flat_adr:
        adr_dir = tmp_path / "adr"
    else:
        adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "0001-first.md").write_text("First ADR body", encoding="utf-8")
    (adr_dir / "0002-second.md").write_text("Second ADR body", encoding="utf-8")
    if context_name:
        (tmp_path / context_name).write_text(
            "Domain glossary content", encoding="utf-8"
        )
    return tmp_path


def test_load_architecture_context_reads_context_and_sorted_adrs(tmp_path):
    ws = make_workspace(tmp_path)
    ctx = load_architecture_context(str(ws))
    assert "--- CONTEXT.md ---" in ctx
    assert "Domain glossary content" in ctx
    first = ctx.index("--- docs/adr/0001-first.md ---")
    second = ctx.index("--- docs/adr/0002-second.md ---")
    assert first < second
    assert "Second ADR body" in ctx


def test_load_architecture_context_falls_back_to_docs_context(tmp_path):
    ws = make_workspace(tmp_path, context_name="docs-context")
    os.rename(ws / "docs-context", ws / "docs" / "context.md")
    ctx = load_architecture_context(str(ws))
    assert "--- docs" in ctx and "context.md ---" in ctx
    assert "Domain glossary content" in ctx


def test_load_architecture_context_flat_adr_fallback(tmp_path):
    ws = make_workspace(tmp_path, flat_adr=True)
    ctx = load_architecture_context(str(ws))
    assert "--- adr/0001-first.md ---" in ctx
    assert "First ADR body" in ctx


def test_load_architecture_context_missing_everything_warns_and_returns_empty(
    tmp_path,
):
    empty = tmp_path / "bare"
    empty.mkdir()
    ctx = load_architecture_context(str(empty))
    assert ctx == ""


def test_load_architecture_context_skips_non_markdown_and_dirs(tmp_path):
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "0001-real.md").write_text("Real ADR", encoding="utf-8")
    (adr_dir / "notes.txt").write_text("ignored", encoding="utf-8")
    (adr_dir / "sub.md").mkdir()
    (tmp_path / "CONTEXT.md").write_text("Glossary", encoding="utf-8")
    ctx = load_architecture_context(str(tmp_path))
    assert "Real ADR" in ctx
    assert "ignored" not in ctx


def test_load_architecture_context_unreadable_context_file_warns(tmp_path):
    (tmp_path / "CONTEXT.md").write_text("secret-ish", encoding="utf-8")
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "0001-a.md").write_text("ADR body", encoding="utf-8")
    os.chmod(tmp_path / "CONTEXT.md", 0o000)
    try:
        ctx = load_architecture_context(str(tmp_path))
    finally:
        os.chmod(tmp_path / "CONTEXT.md", 0o644)
    assert "ADR body" in ctx
    assert "secret-ish" not in ctx


def test_load_architecture_context_unreadable_adr_aborts_dir_reading(tmp_path):
    # Fail-soft contract: a single unreadable ADR file aborts reading the
    # whole ADR directory (loop-level except); the context file, which is
    # read before the ADR block, survives.
    (tmp_path / "CONTEXT.md").write_text("Glossary", encoding="utf-8")
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "0001-a.md").write_text("unreachable body", encoding="utf-8")
    (adr_dir / "0002-b.md").write_text("readable body", encoding="utf-8")
    os.chmod(adr_dir / "0001-a.md", 0o000)
    try:
        ctx = load_architecture_context(str(tmp_path))
    finally:
        os.chmod(adr_dir / "0001-a.md", 0o644)
    assert "Glossary" in ctx
    assert "unreachable body" not in ctx
    assert "readable body" not in ctx


def test_load_architecture_context_unreadable_flat_adr_warns(tmp_path):
    # Same fail-soft contract for the flat adr/ fallback layout.
    (tmp_path / "CONTEXT.md").write_text("Glossary", encoding="utf-8")
    flat_adr = tmp_path / "adr"
    flat_adr.mkdir()
    (flat_adr / "0001-a.md").write_text("unreachable body", encoding="utf-8")
    os.chmod(flat_adr / "0001-a.md", 0o000)
    try:
        ctx = load_architecture_context(str(tmp_path))
    finally:
        os.chmod(flat_adr / "0001-a.md", 0o644)
    assert "Glossary" in ctx
    assert "unreachable body" not in ctx


# ------------------------- prompt identity contract -------------------------


def test_judge_adapter_uses_snapshot_prompts():
    # The eval suite must calibrate exactly the snapshotted judge prompts
    # (ADR-0022); a divergence here would silently invalidate the suite.
    # Compare on observable content (==), not object identity, so any
    # implementation that produces the canonical prompt text stays valid.
    from planner.eval.judge import JUDGE_PROMPTS

    assert JUDGE_PROMPTS["syntax_lint"] == SYSTEM_PROMPT_SYNTAX_LINT
    assert JUDGE_PROMPTS["test_coverage"] == SYSTEM_PROMPT_TEST_COVERAGE
    assert JUDGE_PROMPTS["architecture"] == SYSTEM_PROMPT_ARCH
    assert JUDGE_PROMPTS["security"] == SYSTEM_PROMPT_SECURITY


def test_snapshot_prompts_are_non_empty_strings():
    for prompt in (
        SYSTEM_PROMPT_SYNTAX_LINT,
        SYSTEM_PROMPT_TEST_COVERAGE,
        SYSTEM_PROMPT_ARCH,
        SYSTEM_PROMPT_SECURITY,
    ):
        assert isinstance(prompt, str) and len(prompt) > 0
        assert "<reasoning>" in prompt and "<findings>" in prompt
