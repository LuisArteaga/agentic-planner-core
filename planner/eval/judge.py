"""Importable binary-judge adapter for the eval suite.

Exposes :func:`judge` — the ``judge(diff, judge_type) -> BINEVALResult``
interface demanded by issue #43 as the precursor to a shared
``agentic-judge-core`` library. It reuses the canonical judge artifacts —
the system prompts and the ``<reasoning>``/``<findings>`` XML-tag parser —
directly from the toolkit's importable judge package
``quality_gates_toolkit.review`` (toolkit D-0017, ADR-0022 follow-up), so
the eval suite calibrates exactly the prompts and parser the CI judges run,
and drives the LLM call through the eval suite's streaming OpenRouter client
so that TTFT and cost are captured.

Only the four homogeneous binary PR judges (ADR-0008 fail-fast pipeline)
share the ``judge(diff, judge_type)`` contract. ``evaluate_grade`` is a
numeric option-grader with a different transport and schema and is therefore
out of scope (see ADR-0017).
"""

from __future__ import annotations

import json
import os
from typing import Optional

from quality_gates_toolkit.review import (
    JUDGE_KEYS,
    JUDGE_PROMPTS,
    augment_judge_prompt,
    evaluate_response,
    load_architecture_context,
)

from planner.config import resolve_model_config
from planner.eval.models import BINEVALResult, JudgeMetrics
from planner.eval.openrouter import stream_completion

# Verdict -> passed mapping mirrors ADR-0014: only PASS is "passed".
_VERDICT_TO_PASSED = {"Pass": True}


# Canonical order of the binary judges (ADR-0008 fail-fast pipeline), sourced
# from the toolkit so the suite can never drift from the CI judge set.
BINARY_JUDGE_TYPES = JUDGE_KEYS


def judge(
    diff: str,
    judge_type: str,
    model_override: Optional[str] = None,
    api_key: Optional[str] = None,
    workspace_dir: Optional[str] = None,
) -> tuple:
    """Run a single binary judge over a diff.

    Returns ``(result, metrics)`` where ``result`` is a
    :class:`~planner.eval.models.BINEVALResult` and ``metrics`` is the
    :class:`~planner.eval.models.JudgeMetrics` (TTFT / cost / tokens).

    ``temperature`` is forced to ``0.0`` per issue #43 (deterministic eval).
    A ``model_override`` (the ``--model`` CLI arg) takes precedence over
    ``config/factory.json``; when used, provider routing is disabled so the
    exact model is exercised.
    """
    if judge_type not in JUDGE_PROMPTS:
        raise ValueError(
            f"Unknown binary judge type '{judge_type}'. "
            f"Supported: {sorted(JUDGE_PROMPTS)}"
        )

    cfg = resolve_model_config(judge_type)
    model = model_override or cfg["model"]
    # Eval invariant: deterministic. Force temperature=0.0 (issue #43).
    temperature = 0.0
    # An explicit model override bypasses provider routing to test the
    # exact model rather than a routing fallback chain.
    routing = None if model_override else cfg["routing"]
    options = cfg["options"]
    max_tokens = cfg.get("max_tokens")

    # Mirror the CI judge's prompt construction (toolkit review.py): the
    # composed JUDGE_PROMPTS entry (neutrality frame + judge prompt), then
    # the toolkit's shared augmentation dispatch — called unguarded, exactly
    # like the CI entrypoint. The loader is internally fail-soft (per-file
    # errors degrade to warnings, missing context returns ""). The eval
    # adapter has no deterministic py_compile fixture for its synthetic
    # diffs, so syntax_result is None; the architecture judge receives the
    # workspace context exactly as the CI judge would (context header and
    # missing-context fallback included).
    arch_context = ""
    if judge_type == "architecture" and workspace_dir:
        arch_context = load_architecture_context(workspace_dir)
    system_prompt = augment_judge_prompt(
        judge_type, JUDGE_PROMPTS[judge_type], None, arch_context
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": diff},
    ]

    key: str = api_key or os.getenv("OPENROUTER_API_KEY") or ""
    try:
        content, metrics = stream_completion(
            model=model,
            messages=messages,
            api_key=key,
            routing=routing,
            options=options,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    except Exception as e:  # noqa: BLE001
        return (
            BINEVALResult(
                judge_type=judge_type,
                status="FAIL",
                passed=False,
                error=str(e),
                model=model,
            ),
            JudgeMetrics(),
        )

    # Reuse the toolkit's parser (quality_gates_toolkit.review.
    # evaluate_response), which expects the full OpenRouter response body
    # (choices[].message.content).
    # The streaming client returns only the assembled content, so reconstruct
    # the minimal envelope the parser reads.
    response_body = json.dumps({"choices": [{"message": {"content": content}}]})
    verdict, reasoning, findings = evaluate_response(response_body)
    passed = _VERDICT_TO_PASSED.get(verdict, False)
    status = {"Pass": "PASS", "Fail": "FAIL"}.get(verdict, "NEEDS REVIEW")

    result = BINEVALResult(
        judge_type=judge_type,
        status=status,
        passed=passed,
        reasoning=reasoning,
        findings=findings,
        raw_response=content,
        model=model,
    )
    return result, metrics
