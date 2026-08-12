"""Zero-Error-Tolerance Validation AddOn.

Optional deterministic quality gates (``--zero-tolerance`` CLI flag) that run
before and during refinement. Core lints are fully deterministic (no LLM); the
Intent Gate and Planning Judge are LLM-based final audits. Any violation halts
the entire batch and hands control back to the human (HITL) instead of
auto-fixing.

Inspired by the Fable Method (Think / Act / Prove), adapted to planning-time
constraints — see ADR-0019.
"""

from planner.zero_tolerance.models import (
    BatchValidationResult,
    GlossaryEntry,
    LintFinding,
    Severity,
    ZeroToleranceConfig,
    ZeroToleranceViolation,
)

__all__ = [
    "BatchValidationResult",
    "GlossaryEntry",
    "LintFinding",
    "Severity",
    "ZeroToleranceConfig",
    "ZeroToleranceViolation",
]
