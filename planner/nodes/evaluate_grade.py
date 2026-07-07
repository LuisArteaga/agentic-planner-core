import logging
from pathlib import Path
from typing import Dict, Any, List
from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage
from planner.state import RefinementState
from scripts.telemetry import orchestrator_phase
from planner.config import get_llm


logger = logging.getLogger("planner.nodes.evaluate_grade")


class GradingOption(BaseModel):
    """Grading schema for a single option."""

    choice_id: str = Field(description="Eindeutige ID der Option")
    score: float = Field(
        description="Bewertung von 0.0 bis 10.0 basierend auf der Rubrik"
    )
    reasoning: str = Field(
        description="Detaillierte Begründung unter Bezugnahme auf Rubrik und ADRs"
    )
    checks: Dict[str, bool] = Field(
        default_factory=dict,
        description="Die 10 atomaren Checks (BinEval) für Completeness, Simplicity, ADRs, Robustness",
    )


class CriticEvaluation(BaseModel):
    """Wrapper schema for all evaluations."""

    evaluations: List[GradingOption]


def load_adrs(adr_dir: str = "docs/adr") -> str:
    """Reads all markdown ADR files in docs/adr."""
    adr_path = Path(adr_dir)
    if not adr_path.exists():
        return ""
    adrs = []
    for f in sorted(adr_path.glob("*.md")):
        try:
            with open(f, "r", encoding="utf-8") as file:
                adrs.append(f"### {f.name}\n{file.read()}")
        except Exception as e:
            logger.warning(f"Failed to read ADR {f}: {e}")
    return "\n\n".join(adrs)


def load_rubric(rubric_path: str = "config/grading_rubric.md") -> str:
    """Reads the local grading rubric file."""
    path = Path(rubric_path)
    if not path.exists():
        return ""
    try:
        with open(path, "r", encoding="utf-8") as file:
            return file.read()
    except Exception as e:
        logger.warning(f"Failed to read rubric {path}: {e}")
        return ""


def evaluate_grade_node(state: RefinementState) -> Dict[str, Any]:
    """Node that evaluates and grades proposed options using a Critic LLM call."""
    logger.info("Running evaluate_grade node...")

    with orchestrator_phase("evaluate_grade"):
        proposed_options = state.get("proposed_options", [])
        if not proposed_options:
            logger.warning("No options to grade.")
            return {"best_option": {}, "all_grades": [], "status": "failed"}

        # Load rubric, ADRs, and AgDRs
        rubric_content = load_rubric()
        adr_content = load_adrs("docs/adr")
        agdr_content = load_adrs("docs/agdr")

        combined_decisions = ""
        if adr_content:
            combined_decisions += f"Existing human ADRs:\n{adr_content}\n\n"
        if agdr_content:
            combined_decisions += f"Existing agent AgDRs:\n{agdr_content}\n\n"

        # Instantiate Critic LLM using get_llm
        model = get_llm("evaluate_grade")

        # Set up structured output including raw message for token metadata
        structured_model = model.with_structured_output(
            CriticEvaluation, include_raw=True
        )

        system_instruction = (
            "You are a Senior Software Quality Engineer acting as an independent Critic.\n"
            "Your task is to grade the proposed technical options against the local Grading Rubric "
            "and all existing Architecture Decision Records (ADRs) and Agent Decision Records (AgDRs) of the repository.\n\n"
            "CRITICAL INSTRUCTIONS:\n"
            "1. Use the BinEval framework. For each option, evaluate the 10 atomic binary checks "
            "listed in the rubric. Set each check to true (passed) or false (failed).\n"
            "2. Compute the final score (0.0 to 10.0) strictly based on the proportion of checks passed: "
            "(checks_passed / 10.0) * 10.0.\n"
            "3. If two options receive the same score, you MUST apply a clear prioritization logic "
            "favoring the option with lower complexity (Radical Simplicity / YAGNI). If needed, give the simpler "
            "option a minor score bump (+0.1) or clearly document the tie-breaker choice in the reasoning.\n"
            "4. If existing ADRs or AgDRs contain contradictory guidelines, you MUST explicitly document this contradiction "
            "in the 'reasoning' field of the affected options.\n"
            "5. Ground your review in the provided ADRs/AgDRs and rubric. Do not rely on external undocumented assumptions."
        )

        user_message = (
            f"Grading Rubric:\n{rubric_content}\n\n"
            f"Existing Decisions (ADRs & AgDRs):\n{combined_decisions if combined_decisions else 'No decisions defined.'}\n\n"
            f"Proposed Options to Grade:\n"
        )
        for opt in proposed_options:
            user_message += (
                f"- Option ID: {opt.get('choice_id')}\n"
                f"  Name: {opt.get('name')}\n"
                f"  Description: {opt.get('description')}\n"
                f"  Anticipated Criticism: {opt.get('anticipated_criticism')}\n\n"
            )

        messages = list(state.get("messages", []))
        prompt_tokens = 0
        completion_tokens = 0
        last_error = None
        evaluation_result = None

        # Custom in-node retry loop (up to 3 attempts)
        for attempt in range(1, 4):
            try:
                logger.info(f"Structured evaluation attempt {attempt}/3...")
                if attempt == 1:
                    response = structured_model.invoke(
                        [
                            SystemMessage(content=system_instruction),
                            HumanMessage(content=user_message),
                        ]
                    )
                else:
                    # Retry prompting with error info
                    retry_user_message = (
                        f"{user_message}\n\n"
                        f"WARNING: Your previous attempt failed validation with the following error:\n"
                        f"{last_error}\n"
                        f"Please correct any formatting/schema errors and output a valid JSON structure matching the schema."
                    )
                    response = structured_model.invoke(
                        [
                            SystemMessage(content=system_instruction),
                            HumanMessage(content=retry_user_message),
                        ]
                    )

                # If successful, extract parsed output and raw response metadata
                if response and isinstance(response, dict):
                    parsed_val = response.get("parsed")
                    raw_msg = response.get("raw")
                    if isinstance(parsed_val, CriticEvaluation):
                        evaluation_result = parsed_val
                        if (
                            raw_msg
                            and hasattr(raw_msg, "response_metadata")
                            and raw_msg.response_metadata
                        ):
                            token_usage = raw_msg.response_metadata.get(
                                "token_usage", {}
                            )
                            prompt_tokens = token_usage.get("prompt_tokens", 0)
                            completion_tokens = token_usage.get("completion_tokens", 0)
                        break
                    else:
                        last_error = f"Parsed value was not a CriticEvaluation instance (it was {type(parsed_val)}: {parsed_val})"

            except Exception as e:
                logger.warning(f"Attempt {attempt} failed with error: {e}")
                last_error = str(e)

        if not evaluation_result:
            raise ValueError(
                f"Critic evaluation failed to produce valid structured output after 3 attempts. Last error: {last_error}"
            )

        # Parse output and select the best option
        evaluations_list = [
            {
                "choice_id": ev.choice_id,
                "score": ev.score,
                "reasoning": ev.reasoning,
                "checks": ev.checks,
            }
            for ev in evaluation_result.evaluations
        ]

        if not evaluations_list:
            logger.warning("Critic returned empty evaluations list.")
            return {"best_option": {}, "all_grades": [], "status": "failed"}

        # Tie-breaker & extraction in Python
        # Sort by score descending. If scores are equal, sort by choice_id alphabetically to be deterministic
        sorted_evals = sorted(
            evaluations_list,
            key=lambda x: (
                x["score"],
                -len(str(x.get("reasoning", ""))),
            ),  # Secondary tie break: reasoning depth
            reverse=True,
        )

        best_option = sorted_evals[0]

        return {
            "messages": messages,
            "all_grades": evaluations_list,
            "best_option": best_option,
            "prompt_tokens": state.get("prompt_tokens", 0) + prompt_tokens,
            "completion_tokens": state.get("completion_tokens", 0) + completion_tokens,
            "status": "success",
        }
