"""Calibration contract between the eval judge adapter and the CI judges.

The eval suite must calibrate exactly the artifacts the CI judges run
(ADR-0022 follow-up, toolkit D-0017): the adapter's sent system message is
built from the toolkit's composed ``JUDGE_PROMPTS`` (neutrality frame + judge
prompt) through the toolkit's shared augmentation dispatch — never from a
local copy. Verified through ``judge()``'s observable behavior — the
messages it sends to the LLM — with the OpenRouter transport mocked so the
tests run offline.

Parser verdict branches and context-loader semantics are owned by the
toolkit's own test suite (toolkit ``tests/test_review.py``) and are
deliberately NOT duplicated here; only the adapter-level contract lives in
this file.
"""

from unittest.mock import patch

from quality_gates_toolkit.review import JUDGE_KEYS, JUDGE_PROMPTS

from planner.eval.judge import BINARY_JUDGE_TYPES, judge
from planner.eval.models import JudgeMetrics


def _make_stream(content="<reasoning>all good</reasoning>\n<findings></findings>"):
    return (content, JudgeMetrics())


# The three judges whose prompts the toolkit passes through un-augmented in
# the eval adapter's configuration (no deterministic syntax fixture here).
UNAUGMENTED_JUDGES = ["syntax_lint", "test_coverage", "security"]


def test_binary_judge_types_mirror_toolkit_judge_keys():
    # Single source of truth: the planner's canonical order IS the toolkit's
    # judge set, so the suite can never drift from the CI judge set.
    assert list(BINARY_JUDGE_TYPES) == list(JUDGE_KEYS)


def test_judge_sends_canonical_toolkit_prompts():
    # Calibration contract: for every judge the toolkit passes through
    # un-augmented, the adapter must send the toolkit's composed prompt
    # verbatim — same source object the CI judge sends.
    with patch("planner.eval.judge.stream_completion") as mock_stream:
        mock_stream.return_value = _make_stream()
        for judge_type in UNAUGMENTED_JUDGES:
            mock_stream.reset_mock()
            result, _ = judge("diff content", judge_type, model_override="test/model")
            assert result.passed is True
            messages = mock_stream.call_args.kwargs["messages"]
            assert messages[0]["role"] == "system"
            assert messages[0]["content"] == JUDGE_PROMPTS[judge_type]
            assert messages[1] == {"role": "user", "content": "diff content"}


def test_judge_architecture_uses_ci_augmentation_with_workspace_context(tmp_path):
    # The architecture judge enriches its prompt through the toolkit's
    # augmentation dispatch, exactly like the CI judge: base prompt first,
    # then the workspace's architecture context.
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "0001-first.md").write_text("First ADR body", encoding="utf-8")
    (tmp_path / "docs" / "context.md").write_text(
        "Domain glossary content", encoding="utf-8"
    )
    with patch("planner.eval.judge.stream_completion") as mock_stream:
        mock_stream.return_value = _make_stream()
        result, _ = judge(
            "diff content",
            "architecture",
            model_override="test/model",
            workspace_dir=str(tmp_path),
        )
        assert result.passed is True
        sent = mock_stream.call_args.kwargs["messages"][0]["content"]
        assert JUDGE_PROMPTS["architecture"] in sent
        assert sent.index(JUDGE_PROMPTS["architecture"]) < sent.index(
            "Domain glossary content"
        )
        assert sent.index(JUDGE_PROMPTS["architecture"]) < sent.index("First ADR body")


def test_judge_architecture_without_workspace_keeps_ci_fallback_semantics():
    # Without a workspace the adapter still goes through the toolkit's
    # augmentation dispatch (which appends its missing-context fallback), so
    # the calibration target stays the CI-constructed prompt.
    with patch("planner.eval.judge.stream_completion") as mock_stream:
        mock_stream.return_value = _make_stream()
        result, _ = judge("diff content", "architecture", model_override="test/model")
        assert result.passed is True
        sent = mock_stream.call_args.kwargs["messages"][0]["content"]
        assert JUDGE_PROMPTS["architecture"] in sent
        assert "REPOSITORY ARCHITECTURE CONTEXT" in sent


def test_judge_parses_toolkit_parser_verdict_into_bineval_result():
    # Envelope contract: the adapter reconstructs the OpenRouter body
    # (choices[].message.content) and maps the toolkit parser's verdicts.
    failing = (
        "<reasoning>bad</reasoning>\n"
        '<findings>{"severity": "error", "message": "[Q1] missing"}</findings>'
    )
    with patch("planner.eval.judge.stream_completion") as mock_stream:
        mock_stream.return_value = _make_stream(failing)
        result, _ = judge("diff content", "test_coverage", model_override="test/model")
        assert result.status == "FAIL"
        assert result.passed is False
        assert result.findings == ["error|[Q1] missing"]
