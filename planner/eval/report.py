"""Eval reporting: Markdown job-summary table + ``results.json`` artifact.

Per issue #43 acceptance criteria the results are emitted in three ways:
Markdown to ``$GITHUB_STEP_SUMMARY``, a ``results.json`` artifact, and OTel
traces (the traces are emitted by the runner, not here).
"""

from __future__ import annotations

import os
from typing import Optional

from planner.eval.models import EvalRunResult


def to_json(result: EvalRunResult) -> str:
    """Serialize an :class:`EvalRunResult` to a JSON string."""
    return result.model_dump_json(indent=2)


def _fmt_opt(value: Optional[float], places: int = 3) -> str:
    if value is None:
        return "null"
    return f"{value:.{places}f}"


def to_markdown(result: EvalRunResult) -> str:
    """Render an eval result as a GitHub-Flavored Markdown summary table."""
    lines: list[str] = []
    lines.append(f"### 🧪 LLM-Judge Eval: `{result.judge_type}`\n")
    lines.append(f"**Model**: `{result.model}`  ")
    lines.append(f"**Samples**: {result.sample_count}\n")
    lines.append("| Metric | Value |")
    lines.append("| :--- | :--- |")
    lines.append(f"| Cohen's Kappa | {_fmt_opt(result.cohen_kappa)} |")
    lines.append(f"| MAE | {_fmt_opt(result.mae)} |")
    lines.append(f"| Hard Flips | {result.hard_flip_count} |")
    vb = (
        f"{_fmt_opt(result.verbosity_bias_r)} "
        f"{'⚠️ flagged' if result.verbosity_bias_flagged else ''}".strip()
    )
    lines.append(f"| Verbosity Bias (r) | {vb} |")
    lines.append(f"| Total Cost (USD) | {_fmt_opt(result.total_cost_usd, 4)} |")
    lines.append(f"| Avg Cost / Sample (USD) | {_fmt_opt(result.avg_cost_usd, 4)} |")
    lines.append(f"| TTFT Median (s) | {_fmt_opt(result.ttft_median)} |")
    lines.append(f"| TTFT P95 (s) | {_fmt_opt(result.ttft_p95)} |")
    lines.append("")

    if result.hard_flip_ids:
        lines.append("**Hard-flip samples:**")
        for sid in result.hard_flip_ids:
            lines.append(f"- `{sid}`")
        lines.append("")

    if result.samples:
        lines.append("#### Per-sample detail")
        lines.append(
            "| Sample | Passed | Expected | Score | Expected | Flip | TTFT (s) | Cost (USD) |"
        )
        lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
        for s in result.samples:
            lines.append(
                f"| `{s.sample_id}` | {s.passed} | {s.expected_passed} | "
                f"{_fmt_opt(s.score)} | {_fmt_opt(s.expected_score)} | "
                f"{s.is_hard_flip} | {_fmt_opt(s.metrics.ttft_seconds)} | "
                f"{_fmt_opt(s.metrics.cost_usd, 4)} |"
            )
        lines.append("")

    lines.append(
        "> No automatic gate — metrics serve human evaluation of model swaps "
        "per issue #43.\n"
    )
    return "\n".join(lines)


def write_summary(result: EvalRunResult, path: Optional[str] = None) -> Optional[str]:
    """Append the Markdown table to ``$GITHUB_STEP_SUMMARY`` if available.

    Returns the written path, or ``None`` when not running in GitHub Actions.
    """
    md = to_markdown(result)
    summary_path = path or os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return None
    with open(summary_path, "a", encoding="utf-8") as f:
        f.write(md + "\n")
    return summary_path


def write_results_json(result: EvalRunResult, path: str = "results.json") -> str:
    """Write the ``results.json`` artifact and return its path."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(to_json(result))
    return path
