"""LLM-based Intent Gate node (Fable Method 'Intent Gate', planning-time adaptation).

Before an issue is published, the agent must emit an INTENT line verbatim::

    INTENT: draft issue assumes <X>; target system/code shows <Y>;
    PRD/Glossary/ADR says <Z>

If X, Y, and Z do not agree, the gate flags a 'Surprise' and halts the entire
batch (HITL) instead of auto-fixing.
"""

import logging
from typing import Any, Dict, List

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from planner.config import get_llm
from planner.state import RefinementState
from planner.utils import extract_finish_reason
from planner.zero_tolerance.models import ZeroToleranceViolation
from scripts.telemetry import orchestrator_phase

logger = logging.getLogger("planner.zero_tolerance.intent_gate")


class IntentGateOutput(BaseModel):
    """Structured output of the Intent Gate LLM call."""

    intent_line: str = Field(
        description=(
            "The verbatim INTENT line following: "
            "'INTENT: draft issue assumes <X>; target system/code shows <Y>; "
            "PRD/Glossary/ADR says <Z>'."
        )
    )
    assumptions: str = Field(description="What the draft issue assumes (X).")
    system_state: str = Field(
        description=(
            "What the target system/code actually shows, grounded in the web "
            "search results (Y)."
        )
    )
    spec_state: str = Field(description="What the PRD/Glossary/ADR says (Z).")
    agreement: bool = Field(description="True iff X, Y, and Z are mutually consistent.")
    contradictions: str = Field(
        description=(
            "If agreement is false, describe the contradiction precisely. "
            "Empty otherwise."
        )
    )


def _build_search_context(search_results: List[Dict[str, Any]]) -> str:
    if not search_results:
        return "No web search results available."
    lines = []
    for r in search_results[:10]:
        lines.append(
            f"- Title: {r.get('title', '')}\n  URL: {r.get('url', '')}\n"
            f"  Snippet: {r.get('snippet', '')}"
        )
    return "\n".join(lines)


def intent_gate_node(state: RefinementState) -> Dict[str, Any]:
    """Generate the INTENT line and halt on contradiction."""
    logger.info("Running intent_gate node...")
    with orchestrator_phase("zero_tolerance_intent_gate"):
        from pathlib import Path

        from planner.nodes.evaluate_grade import load_adrs
        from planner.zero_tolerance.linters import parse_scope

        draft_path = state.get("draft_issue_path", "")
        issue_name = Path(draft_path).name if draft_path else "(unknown)"

        # Read the refined content from disk (apply_decision wrote it there).
        refined_content = ""
        if draft_path and Path(draft_path).exists():
            refined_content = Path(draft_path).read_text(encoding="utf-8")
        if not refined_content:
            refined_content = state.get("draft_issue_content", "")

        search_results = state.get("search_results", []) or []
        best_option = state.get("best_option", {}) or {}

        # Load spec context (PRD + glossary + ADRs).
        prd = ""
        prd_path = Path("PRD.md")
        if prd_path.exists():
            prd = prd_path.read_text(encoding="utf-8")[:4000]
        glossary = ""
        context_path = Path("CONTEXT.md")
        if context_path.exists():
            glossary = context_path.read_text(encoding="utf-8")[:4000]
        adr_content = load_adrs("docs/adr")
        agdr_content = load_adrs("docs/agdr")
        decisions = (adr_content + "\n\n" + agdr_content).strip()

        scope = parse_scope(refined_content)

        system_instruction = (
            "You are the Intent Gate of a Zero-Error-Tolerance planning pipeline.\n"
            "Your task is to emit the INTENT line verbatim and judge whether the "
            "draft issue's assumptions (X), the target system/code evidence from "
            "web search (Y), and the specification PRD/Glossary/ADR (Z) agree.\n\n"
            "Rules:\n"
            "1. The 'intent_line' MUST follow exactly: "
            "'INTENT: draft issue assumes <X>; target system/code shows <Y>; "
            "PRD/Glossary/ADR says <Z>'.\n"
            "2. Set 'agreement' to true ONLY if X, Y, and Z are mutually "
            "consistent. Any contradiction (e.g. the draft assumes a library the "
            "search shows is deprecated, or the spec mandates a different pattern) "
            "means agreement is false.\n"
            "3. When agreement is false, fill 'contradictions' with a precise "
            "description of the disagreement.\n"
            "4. Ground Y strictly in the provided web search results; ground Z "
            "strictly in the provided PRD/Glossary/ADR. Do not invent evidence.\n"
        )

        user_message = (
            f"Draft Issue (scope={scope or 'unknown'}):\n{refined_content}\n\n"
            f"Chosen option: {best_option.get('name', '')} "
            f"(score {best_option.get('score', 0.0)})\n\n"
            f"Web search evidence (Y):\n{_build_search_context(search_results)}\n\n"
            f"PRD excerpt (Z):\n{prd or 'No PRD found.'}\n\n"
            f"Glossary excerpt (Z):\n{glossary or 'No glossary found.'}\n\n"
            f"Existing decisions (Z):\n{decisions or 'None.'}\n\n"
            f"Emit the structured INTENT gate output."
        )

        model = get_llm("intent_gate")
        structured_model = model.with_structured_output(
            IntentGateOutput, include_raw=True, strict=True
        )

        result = None
        last_error = None
        for attempt in range(1, 4):
            try:
                logger.info(f"Intent gate attempt {attempt}/3...")
                content = user_message
                if attempt > 1 and last_error:
                    content = (
                        f"{user_message}\n\nWARNING: previous attempt failed: "
                        f"{last_error}\nOutput valid JSON matching the schema."
                    )
                response = structured_model.invoke(
                    [
                        SystemMessage(content=system_instruction),
                        HumanMessage(content=content),
                    ]
                )
                if response and isinstance(response, dict):
                    parsed = response.get("parsed")
                    if isinstance(parsed, IntentGateOutput):
                        result = parsed
                        break
                    raw = response.get("raw")
                    last_error = (
                        str(response.get("parsing_error"))
                        or f"not IntentGateOutput (finish_reason={extract_finish_reason(raw)})"
                    )
            except Exception as exc:
                last_error = str(exc)
                logger.warning(f"Intent gate attempt {attempt} failed: {exc}")

        if not result:
            raise ZeroToleranceViolation(
                "intent_gate",
                f"Failed to produce structured output after 3 attempts: {last_error}",
                issue_name,
            )

        if not result.agreement:
            raise ZeroToleranceViolation(
                "intent_gate",
                f"Intent contradiction (Surprise): {result.contradictions}",
                issue_name,
            )

        logger.info(f"Intent gate passed: {result.intent_line}")
        return {"intent_line": result.intent_line}
