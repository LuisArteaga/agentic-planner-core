"""LLM-based Planning Judge node (Fable Method 'fable-judge', planning-time adaptation).

A final audit step before publishing: the judge treats the refined issue as a
hypothesis and verifies it against the specification (PRD, glossary, ADRs, and
search evidence). A failed verdict halts the entire batch (HITL).
"""

import logging
from pathlib import Path
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from planner.state import RefinementState
from planner.utils import active_search_results
from planner.zero_tolerance.llm_utils import (
    build_search_context,
    invoke_structured_with_retry,
)
from planner.zero_tolerance.models import ZeroToleranceViolation
from scripts.telemetry import orchestrator_phase

logger = logging.getLogger("planner.zero_tolerance.planning_judge")


class PlanningJudgeOutput(BaseModel):
    """Structured output of the Planning Judge LLM call."""

    passed: bool = Field(
        description=(
            "True iff the refined issue is a sound, spec-compliant hypothesis "
            "ready for publishing."
        )
    )
    verdict: str = Field(description="One-paragraph audit verdict.")
    issues: List[str] = Field(
        default_factory=list,
        description="Concrete problems found, empty if passed.",
    )


def planning_judge_node(state: RefinementState) -> Dict[str, Any]:
    """Final audit of the refined issue against the specification."""
    logger.info("Running planning_judge node...")
    with orchestrator_phase("zero_tolerance_planning_judge"):
        from planner.nodes.evaluate_grade import load_adrs

        draft_path = state.get("draft_issue_path", "")
        issue_name = Path(draft_path).name if draft_path else "(unknown)"

        refined_content = ""
        if draft_path and Path(draft_path).exists():
            refined_content = Path(draft_path).read_text(encoding="utf-8")
        if not refined_content:
            refined_content = state.get("draft_issue_content", "")

        search_results = active_search_results(state)
        intent_line = state.get("intent_line", "")

        prd = ""
        prd_path = Path("PRD.md")
        if prd_path.exists():
            prd = prd_path.read_text(encoding="utf-8")[:4000]
        decisions = (load_adrs("docs/adr") + "\n\n" + load_adrs("docs/agdr")).strip()

        system_instruction = (
            "You are the Planning Judge of a Zero-Error-Tolerance planning "
            "pipeline (the 'prove' step of the Fable Method, adapted to "
            "planning-time). You treat the refined issue as a HYPOTHESIS and "
            "verify it adversarially against the specification.\n\n"
            "Rules:\n"
            "1. Set 'passed' to true ONLY if the refined issue is internally "
            "consistent, references valid ADRs, its claims are grounded in the "
            "search evidence, and it satisfies the PRD acceptance criteria.\n"
            "2. Be adversarial: prefer false negatives over false positives. A "
            "single ungrounded claim or spec contradiction means 'passed' is false.\n"
            "3. When 'passed' is false, list every concrete problem in 'issues'.\n"
            "4. Do not rewrite the issue; you only audit it.\n"
        )

        user_message = (
            f"Refined issue (hypothesis to audit):\n{refined_content}\n\n"
            f"Intent gate line:\n{intent_line or '(none)'}\n\n"
            f"Search evidence:\n{build_search_context(search_results)}\n\n"
            f"PRD excerpt:\n{prd or 'No PRD found.'}\n\n"
            f"Existing decisions:\n{decisions or 'None.'}\n\n"
            f"Emit the structured audit verdict."
        )

        try:
            result = invoke_structured_with_retry(
                "planning_judge",
                PlanningJudgeOutput,
                system_instruction,
                user_message,
            )
        except ValueError as exc:
            raise ZeroToleranceViolation("planning_judge", str(exc), issue_name)

        if not result.passed:
            detail = "; ".join(result.issues) if result.issues else result.verdict
            raise ZeroToleranceViolation(
                "planning_judge",
                f"Planning judge rejected the issue: {detail}",
                issue_name,
            )

        logger.info("Planning judge passed.")
        return {}
