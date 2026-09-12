"""Tests for the `eval` CLI subcommand in planner/__main__.py.

Covers argument parsing, telemetry lifecycle, success path (exit 0 +
results.json written), error path (exit 1), and the missing-required-arg path.
"""

import os
import sys
from unittest.mock import patch

import pytest

project_root = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from planner.eval.models import EvalRunResult  # noqa: E402


def _make_fake_result():
    return EvalRunResult(
        judge_type="syntax_lint",
        model="test/model",
        sample_count=1,
        cohen_kappa=1.0,
        mae=0.0,
        hard_flip_count=0,
    )


@patch("planner.eval.report.write_summary", return_value=None)
@patch("planner.eval.report.write_results_json")
@patch("planner.eval.runner.run_eval", return_value=_make_fake_result())
@patch("planner.telemetry.end_orchestrator_loop")
@patch("planner.telemetry.start_orchestrator_loop")
@patch("planner.telemetry.init_telemetry")
def test_eval_cli_success(
    mock_init,
    mock_start,
    mock_end,
    mock_run,
    mock_write_json,
    mock_write_summary,
    tmp_path,
    monkeypatch,
):
    """The eval CLI writes results.json and exits 0 on success."""
    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)
    out_json = tmp_path / "results.json"
    mock_write_json.return_value = str(out_json)

    with patch.object(
        sys,
        "argv",
        ["planner", "eval", "--judge", "syntax_lint", "--results-json", str(out_json)],
    ):
        from planner.__main__ import main

        main()  # success path returns normally (no sys.exit on exit_code==0)

    mock_init.assert_called_once()
    mock_start.assert_called_once()
    mock_end.assert_called_once_with(exit_code=0)
    mock_run.assert_called_once()
    # results.json write was invoked with the CLI-provided path.
    call_kwargs = mock_write_json.call_args
    assert str(out_json) in (call_kwargs.kwargs.get("path", "") or call_kwargs.args[1])


@patch("planner.eval.report.write_summary", return_value=None)
@patch("planner.eval.report.write_results_json")
@patch("planner.eval.runner.run_eval", side_effect=RuntimeError("boom"))
@patch("planner.telemetry.end_orchestrator_loop")
@patch("planner.telemetry.start_orchestrator_loop")
@patch("planner.telemetry.init_telemetry")
def test_eval_cli_error_exit_code(
    mock_init,
    mock_start,
    mock_end,
    mock_run,
    mock_write_json,
    mock_write_summary,
    tmp_path,
    monkeypatch,
):
    """A runner error sets exit_code=1 and the telemetry ends with error."""
    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)
    out_json = tmp_path / "results.json"

    with patch.object(
        sys,
        "argv",
        ["planner", "eval", "--judge", "security", "--results-json", str(out_json)],
    ):
        with pytest.raises(SystemExit) as exc:
            from planner.__main__ import main

            main()

    assert exc.value.code == 1
    mock_end.assert_called_once_with(exit_code=1)


def test_eval_cli_missing_judge_arg_exits_nonzero(monkeypatch):
    """Omitting the required --judge flag causes argparse to exit with code 2."""
    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)
    with patch.object(sys, "argv", ["planner", "eval"]):
        with pytest.raises(SystemExit) as exc:
            from planner.__main__ import main

            main()
    assert exc.value.code == 2


@patch("planner.eval.report.write_summary", return_value=None)
@patch("planner.eval.report.write_results_json")
@patch("planner.eval.runner.run_eval", return_value=_make_fake_result())
@patch("planner.telemetry.end_orchestrator_loop")
@patch("planner.telemetry.start_orchestrator_loop")
@patch("planner.telemetry.init_telemetry")
def test_eval_cli_model_override_forwarded(
    mock_init,
    mock_start,
    mock_end,
    mock_run,
    mock_write_json,
    mock_write_summary,
    tmp_path,
    monkeypatch,
):
    """The --model flag is forwarded to run_eval as the model override."""
    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)
    out_json = tmp_path / "results.json"
    mock_write_json.return_value = str(out_json)

    with patch.object(
        sys,
        "argv",
        [
            "planner",
            "eval",
            "--judge",
            "syntax_lint",
            "--model",
            "z-ai/glm-5.2",
            "--results-json",
            str(out_json),
        ],
    ):
        from planner.__main__ import main

        main()  # success path returns normally (no sys.exit on exit_code==0)

    call_kwargs = mock_run.call_args
    assert call_kwargs.kwargs.get("model") == "z-ai/glm-5.2"
