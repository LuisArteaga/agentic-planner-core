"""LLM-Judge regression evaluation suite.

Quantifies every model change in ``config/factory.json`` by running the
configured binary PR judges (``syntax_lint``, ``test_coverage``,
``architecture``, ``security``) against a human-annotated gold-standard
dataset and computing statistical agreement metrics (Cohen's Kappa, MAE,
Hard Flips, Verbosity Bias) alongside OpenRouter cost and TTFT.

See ``docs/adr/0017-evaluate-grade-excluded-from-binary-eval-harness.md``
for why ``evaluate_grade`` is out of scope for this binary harness.
"""

from planner.eval.models import (
    BINEVALResult,
    JudgeMetrics,
    Sample,
    SampleResult,
    EvalRunResult,
)
from planner.eval.judge import judge, BINARY_JUDGE_TYPES
from planner.eval.runner import run_eval

__all__ = [
    "BINEVALResult",
    "JudgeMetrics",
    "Sample",
    "SampleResult",
    "EvalRunResult",
    "judge",
    "BINARY_JUDGE_TYPES",
    "run_eval",
]
