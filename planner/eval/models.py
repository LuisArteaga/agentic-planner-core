"""Typed data models for the LLM-Judge evaluation suite.

These structures are deliberately framework-free (pure dataclasses /
Pydantic) so they can be reused by a future ``agentic-judge-core`` library
without pulling in the planner's LangGraph stack.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class BINEVALResult(BaseModel):
    """The outcome of a single binary judge invocation.

    Mirrors the verdict semantics of ``scripts/review.py``:
    ``status`` is one of ``PASS`` / ``FAIL`` / ``NEEDS REVIEW`` and
    ``passed`` is ``True`` only for ``PASS`` (per ADR-0014 both ``FAIL``
    and ``NEEDS REVIEW`` are merge-blocking, hence not ``passed``).
    """

    judge_type: str
    status: str = "NEEDS REVIEW"
    passed: bool = False
    reasoning: str = ""
    findings: List[str] = Field(default_factory=list)
    raw_response: str = ""
    error: Optional[str] = None
    model: str = ""


class JudgeMetrics(BaseModel):
    """Per-sample OpenRouter transport metrics."""

    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    ttft_seconds: Optional[float] = None
    latency_seconds: Optional[float] = None


class Sample(BaseModel):
    """A single gold-standard fixture entry.

    ``expected_passed`` / ``expected_score`` are the human annotation the
    judge is calibrated against. For the binary PR judges ``expected_score``
    is 0.0 (fail) or 1.0 (pass); for ``evaluate_grade`` it would be 0-10
    (currently unsupported — see ADR-0017).
    """

    id: str
    diff: str
    expected_passed: bool
    expected_score: float
    expected_verdict: str = ""
    diff_token_count: Optional[int] = None
    metadata: dict = Field(default_factory=dict)


class SampleResult(BaseModel):
    """The judged outcome for one sample plus transport metrics."""

    sample_id: str
    judge_type: str
    model: str
    passed: bool
    score: float
    expected_passed: bool
    expected_score: float
    is_hard_flip: bool
    metrics: JudgeMetrics
    error: Optional[str] = None


class EvalRunResult(BaseModel):
    """Aggregate result of an eval run over one judge type."""

    judge_type: str
    model: str
    sample_count: int
    cohen_kappa: Optional[float] = None
    mae: Optional[float] = None
    hard_flip_count: int = 0
    hard_flip_ids: List[str] = Field(default_factory=list)
    verbosity_bias_r: Optional[float] = None
    verbosity_bias_flagged: bool = False
    total_cost_usd: float = 0.0
    avg_cost_usd: Optional[float] = None
    ttft_median: Optional[float] = None
    ttft_p95: Optional[float] = None
    samples: List[SampleResult] = Field(default_factory=list)
