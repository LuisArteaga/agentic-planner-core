"""Pydantic models and the halt-signalling exception for the Zero-Error-Tolerance AddOn."""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class Severity(str, Enum):
    """Severity of a deterministic lint finding."""

    ERROR = "error"
    WARNING = "warning"


class LintFinding(BaseModel):
    """A single deterministic lint finding produced by a zero-tolerance check."""

    check: str = Field(
        description=(
            "The check that produced the finding: 'glossary', 'dependency', "
            "'adr_traceability', 'threshold', 'intent_gate', 'planning_judge', "
            "or 'cascade'."
        )
    )
    severity: Severity
    issue: str = Field(
        description="Draft issue file name or path the finding relates to."
    )
    message: str
    detail: Optional[str] = None


class BatchValidationResult(BaseModel):
    """Aggregate result of the pre-refinement batch validation gate."""

    passed: bool
    findings: List[LintFinding] = Field(default_factory=list)

    def errors(self) -> List[LintFinding]:
        return [f for f in self.findings if f.severity == Severity.ERROR]


class GlossaryEntry(BaseModel):
    """A parsed glossary term with its canonical forms and deprecated synonyms."""

    canonical_terms: List[str] = Field(
        description="Lowercase canonical term forms (heading + parentheticals)."
    )
    deprecated_synonyms: List[str] = Field(
        default_factory=list,
        description=(
            "Lowercase synonyms explicitly marked as deprecated in the glossary "
            "entry's 'Synonyme / Abzugrenzende Begriffe' field via the "
            "'Veraltete Synonyme:' prefix."
        ),
    )


class ZeroToleranceConfig(BaseModel):
    """Configuration for the Zero-Error-Tolerance AddOn.

    All thresholds are deterministic and configurable. The AddOn is enabled
    either via the ``--zero-tolerance`` CLI flag or the ``[zero_tolerance]``
    table in ``sources.toml``.
    """

    enabled: bool = False
    # Deterministic threshold escape hatches (Fable Method: bounded retries).
    min_acceptable_score: float = 5.0
    max_fruitless_searches: int = 0
    # Triviality gate: bypass the LLM gates for trivial draft issues.
    trivial_max_lines: int = 15
    trivial_scopes: List[str] = Field(default_factory=lambda: ["docs"])
    # Source locations (relative to CWD by default, matching existing ADR loading).
    context_path: str = "CONTEXT.md"
    adr_dirs: List[str] = Field(default_factory=lambda: ["docs/adr", "docs/agdr"])


class ZeroToleranceViolation(Exception):
    """Raised when a zero-tolerance gate fails.

    Per the AddOn constraint, a violation halts the ENTIRE batch immediately and
    hands control back to the human (HITL) rather than auto-fixing. The master
    refinement loop re-raises this exception (it does NOT isolate it per-draft).
    """

    def __init__(self, check: str, message: str, issue: str = ""):
        self.check = check
        self.message = message
        self.issue = issue
        super().__init__(
            f"[{check}] {issue}: {message}" if issue else f"[{check}] {message}"
        )
