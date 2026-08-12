"""Shared helpers for the LLM-based zero-tolerance gates.

Extracted to eliminate duplication between ``intent_gate`` and
``planning_judge`` (both run the same structured-output retry loop and build the
same search-evidence context).
"""

import logging
from typing import Any, Dict, List, Type, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from planner.config import get_llm
from planner.utils import extract_finish_reason

logger = logging.getLogger("planner.zero_tolerance.llm_utils")

T = TypeVar("T", bound=BaseModel)


def build_search_context(search_results: List[Dict[str, Any]]) -> str:
    """Render web search results as a compact evidence block.

    Shared by the Intent Gate and Planning Judge so both gates reason over the
    same evidence representation.
    """
    if not search_results:
        return "No web search results available."
    lines = []
    for r in search_results[:10]:
        title = r.get("title", "")
        url = r.get("url", "")
        snippet = r.get("snippet", "")
        lines.append(f"- Title: {title}\n  URL: {url}\n  Snippet: {snippet}")
    return "\n".join(lines)


def invoke_structured_with_retry(
    phase_or_node: str,
    output_type: Type[T],
    system_instruction: str,
    user_message: str,
    max_attempts: int = 3,
) -> T:
    """Invoke a structured-output LLM with a bounded retry loop.

    Runs up to ``max_attempts`` (Fable Method: bounded retries). On a parse
    failure, re-prompts with the parsing error so the model can self-correct.
    Distinguishes truncation (``finish_reason == "length"``) from malformed JSON
    in the logs, mirroring ``evaluate_grade`` / ``apply_decision``.

    Returns the parsed ``output_type`` instance. Raises ``ValueError`` if all
    attempts fail (the caller wraps it into a ``ZeroToleranceViolation``).
    """
    model = get_llm(phase_or_node)
    structured_model = model.with_structured_output(
        output_type, include_raw=True, strict=True
    )

    last_error: str | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            logger.info(f"{phase_or_node} attempt {attempt}/{max_attempts}...")
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
                if isinstance(parsed, output_type):
                    return parsed
                raw = response.get("raw")
                last_error = (
                    str(response.get("parsing_error"))
                    or f"not {output_type.__name__} (finish_reason={extract_finish_reason(raw)})"
                )
        except Exception as exc:
            last_error = str(exc)
            logger.warning(f"{phase_or_node} attempt {attempt} failed: {exc}")

    raise ValueError(
        f"{phase_or_node} failed to produce structured output after "
        f"{max_attempts} attempts. Last error: {last_error}"
    )
