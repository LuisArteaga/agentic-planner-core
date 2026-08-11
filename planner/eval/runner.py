"""Eval runner: load fixtures, judge each sample, compute aggregate metrics.

Honours ADR-0008 (each judge is evaluated in isolation) and ADR-0009 (every
run emits OTel/Langfuse spans — one ``eval_run`` chain span with the
aggregate metrics and one ``eval_sample`` LLM span per sample). Telemetry is
optional: a missing Langfuse key never raises (ADR-0009).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List, Optional

from opentelemetry.trace import Status, StatusCode

from planner.eval.judge import judge
from planner.eval.models import EvalRunResult, Sample, SampleResult
from planner.eval.stats import (
    cohen_kappa,
    hard_flips,
    mae,
    median,
    p95,
    verbosity_bias,
)
from scripts.telemetry import get_tracer

logger = logging.getLogger("planner.eval.runner")


def load_fixtures(fixtures_dir: str, judge_type: str) -> List[Sample]:
    """Load all ``*.json`` gold-standard samples for a judge type."""
    base = Path(fixtures_dir) / judge_type
    if not base.exists():
        raise FileNotFoundError(
            f"Fixture directory not found: {base}. "
            f"Expected tests/eval/fixtures/{judge_type}/."
        )
    samples: List[Sample] = []
    for path in sorted(base.glob("*.json")):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("id", path.stem)
            samples.append(Sample.model_validate(data))
        except Exception as e:  # noqa: BLE001
            logger.warning("Skipping malformed fixture %s: %s", path, e)
    return samples


def run_eval(
    judge_type: str,
    model: Optional[str] = None,
    fixtures_dir: str = "tests/eval/fixtures",
    api_key: Optional[str] = None,
    workspace_dir: Optional[str] = None,
) -> EvalRunResult:
    """Run the eval suite for a single judge type and return aggregate metrics.

    ``model`` overrides the factory-configured model for the judge (the
    ``--model`` CLI flag). When ``None`` the factory model is used.
    """
    samples = load_fixtures(fixtures_dir, judge_type)

    tracer = get_tracer()
    run_span = tracer.start_span("eval_run")
    run_span.set_attribute("openinference.span.kind", "CHAIN")
    run_span.set_attribute("eval.judge_type", judge_type)
    run_span.set_attribute("eval.model", model or "factory-default")
    run_span.set_attribute("eval.sample_count", len(samples))

    # Resolve the effective model name for reporting even on an empty run.
    from planner.config import resolve_model_config
    from planner.eval.judge import BINARY_JUDGE_TYPES
    from planner.eval.models import JudgeMetrics

    effective_model = model or resolve_model_config(judge_type)["model"]

    # ADR-0017: evaluate_grade (and any non-binary judge) has no binary
    # pass/fail adapter. Load its fixtures for AC compliance but report each
    # sample as "unsupported" rather than crashing (CLI must exit 0).
    if judge_type not in BINARY_JUDGE_TYPES:
        placeholder_results = [
            SampleResult(
                sample_id=s.id,
                judge_type=judge_type,
                model=effective_model,
                passed=s.expected_passed,
                score=s.expected_score,
                expected_passed=s.expected_passed,
                expected_score=s.expected_score,
                is_hard_flip=False,
                metrics=JudgeMetrics(),
                error="No binary adapter for this judge type (ADR-0017).",
            )
            for s in samples
        ]
        run_span.set_attribute("eval.unsupported_judge", True)
        run_span.end()
        return EvalRunResult(
            judge_type=judge_type,
            model=effective_model,
            sample_count=len(placeholder_results),
            samples=placeholder_results,
        )

    results: List[SampleResult] = []
    try:
        for sample in samples:
            sample_span = tracer.start_span(f"eval_sample_{sample.id}")
            sample_span.set_attribute("openinference.span.kind", "LLM")
            sample_span.set_attribute("eval.judge_type", judge_type)
            sample_span.set_attribute("eval.sample_id", sample.id)
            sample_span.set_attribute("llm.model_name", effective_model)

            result, metrics = judge(
                diff=sample.diff,
                judge_type=judge_type,
                model_override=model,
                api_key=api_key,
                workspace_dir=workspace_dir,
            )

            pred_passed = result.passed
            # Binary judges encode their score as 1.0/0.0 (pass/fail).
            pred_score = 1.0 if pred_passed else 0.0
            is_flip = pred_passed != sample.expected_passed

            sample_span.set_attribute("eval.passed", pred_passed)
            sample_span.set_attribute("eval.expected_passed", sample.expected_passed)
            sample_span.set_attribute("eval.is_hard_flip", is_flip)
            if metrics.ttft_seconds is not None:
                sample_span.set_attribute("eval.ttft_seconds", metrics.ttft_seconds)
            if metrics.cost_usd is not None:
                sample_span.set_attribute("eval.cost_usd", metrics.cost_usd)
            if result.error:
                sample_span.record_exception(RuntimeError(result.error))
            sample_span.set_status(
                Status(StatusCode.ERROR if result.error else StatusCode.OK)
            )
            sample_span.end()

            results.append(
                SampleResult(
                    sample_id=sample.id,
                    judge_type=judge_type,
                    model=effective_model,
                    passed=pred_passed,
                    score=pred_score,
                    expected_passed=sample.expected_passed,
                    expected_score=sample.expected_score,
                    is_hard_flip=is_flip,
                    metrics=metrics,
                    error=result.error,
                )
            )
    finally:
        run_span.end()

    return _aggregate(judge_type, effective_model, samples, results)


def _aggregate(
    judge_type: str,
    model: str,
    samples: List[Sample],
    results: List[SampleResult],
) -> EvalRunResult:
    pred_passed = [r.passed for r in results]
    gold_passed = [r.expected_passed for r in results]
    pred_scores = [r.score for r in results]
    gold_scores = [r.expected_score for r in results]

    flip_count, flip_idx = hard_flips(pred_passed, gold_passed)
    flip_ids = [results[i].sample_id for i in flip_idx]

    diff_tokens = [
        float(s.diff_token_count) if s.diff_token_count is not None else 0.0
        for s in samples
    ]
    score_diffs = [abs(p - g) for p, g in zip(pred_scores, gold_scores)]
    vb_r, vb_flagged = verbosity_bias(diff_tokens, score_diffs)

    ttfts = [
        r.metrics.ttft_seconds for r in results if r.metrics.ttft_seconds is not None
    ]
    costs = [r.metrics.cost_usd for r in results if r.metrics.cost_usd is not None]
    total_cost = sum(costs) if costs else 0.0
    avg_cost = (total_cost / len(costs)) if costs else None

    return EvalRunResult(
        judge_type=judge_type,
        model=model,
        sample_count=len(results),
        cohen_kappa=cohen_kappa(pred_passed, gold_passed),
        mae=mae(pred_scores, gold_scores),
        hard_flip_count=flip_count,
        hard_flip_ids=flip_ids,
        verbosity_bias_r=vb_r,
        verbosity_bias_flagged=vb_flagged,
        total_cost_usd=total_cost,
        avg_cost_usd=avg_cost,
        ttft_median=median(ttfts),
        ttft_p95=p95(ttfts),
        samples=results,
    )
