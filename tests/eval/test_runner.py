"""Tests for the eval runner, judge adapter, and report module.

The OpenRouter streaming call is mocked so these tests run offline and fast.
"""

import json
import os
import sys
from unittest.mock import patch

import pytest

# Ensure project root importable
project_root = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from planner.eval.judge import judge  # noqa: E402
from planner.eval.models import BINEVALResult, JudgeMetrics  # noqa: E402
from planner.eval.runner import load_fixtures, run_eval  # noqa: E402
from planner.eval.report import to_json, to_markdown  # noqa: E402


def make_pass_response():
    """An OpenRouter streaming-style result: content with empty findings."""
    content = "<reasoning>all good</reasoning>\n<findings></findings>"
    metrics = JudgeMetrics(
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        cost_usd=0.001,
        ttft_seconds=0.42,
        latency_seconds=1.2,
    )
    return content, metrics


def make_fail_response():
    content = (
        "<reasoning>bad naming</reasoning>\n"
        '<findings>{"severity": "error", "message": "[Q3] missing Hub_ prefix"}'
        "</findings>"
    )
    metrics = JudgeMetrics(
        prompt_tokens=10,
        completion_tokens=8,
        total_tokens=18,
        cost_usd=0.002,
        ttft_seconds=None,  # simulate a non-streaming model
        latency_seconds=1.5,
    )
    return content, metrics


# ------------------------------- Fixtures ----------------------------------


def test_fixtures_exist_syntax_lint():
    samples = load_fixtures("tests/eval/fixtures", "syntax_lint")
    assert len(samples) >= 1
    for s in samples:
        assert s.diff
        assert isinstance(s.expected_passed, bool)


def test_fixtures_exist_test_coverage():
    samples = load_fixtures("tests/eval/fixtures", "test_coverage")
    assert len(samples) >= 1
    for s in samples:
        assert s.diff
        assert isinstance(s.expected_passed, bool)


def test_fixtures_exist_architecture():
    samples = load_fixtures("tests/eval/fixtures", "architecture")
    assert len(samples) >= 1
    for s in samples:
        assert s.diff
        assert isinstance(s.expected_passed, bool)


def test_fixtures_exist_security():
    samples = load_fixtures("tests/eval/fixtures", "security")
    assert len(samples) >= 1
    for s in samples:
        assert s.diff
        assert isinstance(s.expected_passed, bool)


def test_fixture_evaluate_grade_exists():
    # AC: the evaluate_grade fixture dir must exist with one valid sample.
    samples = load_fixtures("tests/eval/fixtures", "evaluate_grade")
    assert len(samples) >= 1


# ------------------------------ judge adapter -------------------------------


@patch("planner.eval.judge.stream_completion")
def test_judge_pass(mock_stream):
    mock_stream.return_value = make_pass_response()
    result, metrics = judge("diff content", "syntax_lint", model_override="test/model")
    assert isinstance(result, BINEVALResult)
    assert result.judge_type == "syntax_lint"
    assert result.passed is True
    assert result.status == "PASS"
    assert result.model == "test/model"
    assert metrics.cost_usd == 0.001


@patch("planner.eval.judge.stream_completion")
def test_judge_fail(mock_stream):
    mock_stream.return_value = make_fail_response()
    result, metrics = judge("diff content", "syntax_lint")
    assert result.passed is False
    assert result.status == "FAIL"
    assert len(result.findings) == 1
    assert metrics.ttft_seconds is None


@patch("planner.eval.judge.stream_completion")
def test_judge_unknown_type_raises(mock_stream):
    mock_stream.return_value = make_pass_response()
    with pytest.raises(ValueError, match="Unknown binary judge type"):
        judge("diff", "evaluate_grade")


@patch("planner.eval.judge.stream_completion")
def test_judge_transport_error_is_failure(mock_stream):
    mock_stream.side_effect = RuntimeError("OpenRouter 500")
    result, metrics = judge("diff", "security")
    assert result.passed is False
    assert result.status == "FAIL"
    assert result.error is not None and "OpenRouter 500" in result.error


# --------------------------------- Runner ----------------------------------


@patch("planner.eval.judge.stream_completion")
def test_run_eval_aggregates_metrics(mock_stream):
    mock_stream.return_value = make_pass_response()
    result = run_eval("syntax_lint", fixtures_dir="tests/eval/fixtures")
    assert result.judge_type == "syntax_lint"
    assert result.sample_count >= 1
    # All samples expected PASS and judge returns PASS => perfect agreement.
    assert result.cohen_kappa is None or result.cohen_kappa == 1.0
    assert result.hard_flip_count == 0
    assert result.total_cost_usd > 0
    assert result.ttft_median == pytest.approx(0.42)
    assert result.verbosity_bias_flagged is False


@patch("planner.eval.judge.stream_completion")
def test_run_eval_detects_hard_flips(mock_stream):
    # Force a FAIL verdict so it disagrees with the PASS gold standard.
    mock_stream.return_value = make_fail_response()
    result = run_eval("syntax_lint", fixtures_dir="tests/eval/fixtures")
    assert result.hard_flip_count >= 1
    assert len(result.hard_flip_ids) == result.hard_flip_count


# ------------------------------- Reporting ---------------------------------


@patch("planner.eval.judge.stream_completion")
def test_report_serialization_roundtrip(mock_stream):
    mock_stream.return_value = make_pass_response()
    result = run_eval("syntax_lint", fixtures_dir="tests/eval/fixtures")
    js = to_json(result)
    parsed = json.loads(js)
    assert parsed["judge_type"] == "syntax_lint"
    md = to_markdown(result)
    assert "Cohen's Kappa" in md
    assert "Hard Flips" in md


def test_run_eval_evaluate_grade_placeholder_exits_gracefully():
    """ADR-0017: evaluate_grade has no binary adapter but the CLI must exit 0."""
    result = run_eval("evaluate_grade", fixtures_dir="tests/eval/fixtures")
    assert result.judge_type == "evaluate_grade"
    assert result.sample_count >= 1
    # No metrics computed for the placeholder; samples carry the ADR note.
    assert result.cohen_kappa is None
    assert result.hard_flip_count == 0
    assert all(s.error is not None and "ADR-0017" in s.error for s in result.samples)
