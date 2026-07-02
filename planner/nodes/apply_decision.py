import os
import logging
import datetime
from pathlib import Path
from typing import Dict, Any
from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from opentelemetry import trace
from planner.state import RefinementState
from scripts.telemetry import orchestrator_phase
from planner.nodes.evaluate_grade import load_adrs

logger = logging.getLogger("planner.nodes.apply_decision")


class ApplyDecisionOutput(BaseModel):
    """Pydantic model for structured decision output from LLM."""

    requires_agdr: bool = Field(
        description="Whether a new Agent Decision Record (AgDR) is required."
    )
    agdr_title: str = Field(
        description="A short kebab-case title slug for the new AgDR (e.g., 'use-sqlite-cache'). Empty if requires_agdr is false."
    )
    agdr_content: str = Field(
        description="The content of the AgDR in markdown format, starting directly with the section '## Kontext und Problemstellung'. Empty if requires_agdr is false."
    )
    updated_issue_content: str = Field(
        description="Complete rewritten draft issue markdown content, preserving all original headers and sections, but enriching them with research findings, grading reasons, and references/links to AgDRs."
    )


def get_next_agdr_number(agdr_dir: Path) -> int:
    """Scan the AgDR directory and return the next free AgDR sequential number."""
    if not agdr_dir.exists():
        return 1
    max_num = 0
    for f in agdr_dir.glob("*.md"):
        name = f.name
        parts = name.split("-", 1)
        if parts[0].isdigit():
            num = int(parts[0])
            if num > max_num:
                max_num = num
    return max_num + 1


def apply_decision_node(state: RefinementState) -> Dict[str, Any]:
    """Node that decides if a new AgDR is required, generates it,

    and rewrites the local draft issue file.
    """
    logger.info("Running apply_decision node...")

    with orchestrator_phase("apply_decision"):
        draft_content = state.get("draft_issue_content", "")
        draft_path_str = state.get("draft_issue_path")
        best_option = state.get("best_option", {})
        all_grades = state.get("all_grades", [])
        search_results = state.get("search_results", [])
        critic_model_name = state.get("model_name", "unknown-model")

        if not draft_path_str:
            logger.warning("No draft_issue_path set in state. Skipping file updates.")
            return {"status": "success"}

        draft_path = Path(draft_path_str).resolve()
        if not draft_path.exists():
            raise FileNotFoundError(f"Draft issue file does not exist: {draft_path}")

        # 1. Load existing ADRs and AgDRs to provide context to the LLM
        workspace_dir = Path(os.environ.get("GITHUB_WORKSPACE", os.getcwd()))
        existing_adrs = load_adrs(str(workspace_dir / "docs" / "adr"))
        existing_agdrs = load_adrs(str(workspace_dir / "docs" / "agdr"))

        combined_decisions = ""
        if existing_adrs:
            combined_decisions += f"Existing human ADRs:\n{existing_adrs}\n\n"
        if existing_agdrs:
            combined_decisions += f"Existing agent AgDRs:\n{existing_agdrs}\n\n"

        # 2. Configure model
        model_name = os.getenv("AGENT_MODEL", "google/gemini-2.5-flash")
        model = ChatOpenAI(
            model=model_name,
            temperature=0.0,
            openai_api_base="https://openrouter.ai/api/v1",
            openai_api_key=os.getenv("OPENROUTER_API_KEY"),
        )

        structured_model = model.with_structured_output(
            ApplyDecisionOutput, include_raw=True
        )

        # 3. Formulate prompts
        system_instruction = (
            "You are a Principal Software Architect.\n"
            "Your task is to analyze the draft issue description and the chosen best option, "
            "then decide if a new Agent Decision Record (AgDR) is required, and rewrite the draft issue content.\n\n"
            "AgDR criteria:\n"
            "An AgDR is required if the decision is hard to reverse, surprising without context, or the result of a real trade-off.\n\n"
            "CRITICAL INSTRUCTIONS:\n"
            "1. Evaluate if the chosen option requires an AgDR. Set 'requires_agdr' accordingly.\n"
            "2. If requires_agdr is true, generate 'agdr_title' (a short kebab-case title slug, e.g. 'use-sqlite-cache') and 'agdr_content'.\n"
            "   The 'agdr_content' MUST follow the standard AgDR format starting with '## Kontext und Problemstellung'. DO NOT include the main title (#) or the metadata list at the top, as those will be prepended by the system.\n"
            "3. Rewrite the draft issue content. You MUST strictly preserve all the original section headers and structure (e.g. ## What to build, ## Scope, ## Constraints, ## Edge cases, ## Acceptance criteria).\n"
            "   Enrich the contents of these sections with:\n"
            "   - Research findings (citing search results and URLs).\n"
            "   - Grading reasons and scores of the evaluated options.\n"
            "   - Clear references or links to any existing ADRs/AgDRs or the newly created AgDR.\n"
            "4. If the refinement yielded no new findings or changes, keep 'updated_issue_content' exactly identical to the original content.\n"
        )

        grades_context = ""
        for grade in all_grades:
            grades_context += (
                f"- Option: {grade.get('choice_id')}\n"
                f"  Score: {grade.get('score')}/10.0\n"
                f"  Reasoning: {grade.get('reasoning')}\n"
                f"  Checks passed: {sum(1 for v in grade.get('checks', {}).values() if v)}/10\n\n"
            )

        search_context = ""
        if search_results:
            search_context = "Web Search Results:\n" + "\n".join(
                [
                    f"- Title: {r.get('title')}\n  URL: {r.get('url')}\n  Snippet: {r.get('snippet')}"
                    for r in search_results
                ]
            )

        user_message = (
            f"Original Draft Issue:\n{draft_content}\n\n"
            f"Chosen Option:\n{best_option}\n\n"
            f"All Graded Options:\n{grades_context}\n"
            f"{search_context}\n\n"
            f"Existing Decisions:\n{combined_decisions if combined_decisions else 'None'}\n\n"
            f"Produce the structured output."
        )

        prompt_tokens = 0
        completion_tokens = 0
        response_data = None
        last_error = None

        # Execute LLM call with retry loop (up to 3 times)
        for attempt in range(1, 4):
            try:
                logger.info(f"Structured decision attempt {attempt}/3...")
                if attempt == 1:
                    response = structured_model.invoke(
                        [
                            SystemMessage(content=system_instruction),
                            HumanMessage(content=user_message),
                        ]
                    )
                else:
                    retry_message = (
                        f"{user_message}\n\n"
                        f"WARNING: Your previous attempt failed with error:\n"
                        f"{last_error}\n"
                        f"Please correct the error and output valid JSON matching the schema."
                    )
                    response = structured_model.invoke(
                        [
                            SystemMessage(content=system_instruction),
                            HumanMessage(content=retry_message),
                        ]
                    )

                if response and isinstance(response, dict):
                    parsed_val = response.get("parsed")
                    raw_msg = response.get("raw")
                    if isinstance(parsed_val, ApplyDecisionOutput):
                        response_data = parsed_val
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
            except Exception as e:
                logger.warning(f"Attempt {attempt} failed: {e}")
                last_error = str(e)

        if not response_data:
            raise ValueError(
                f"Apply decision failed to generate structured output after 3 attempts. Last error: {last_error}"
            )

        # 4. Handle AgDR creation if required
        if response_data.requires_agdr:
            agdr_dir = workspace_dir / "docs" / "agdr"
            try:
                agdr_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                raise IOError(f"Failed to create AgDR directory at {agdr_dir}: {e}")

            next_num = get_next_agdr_number(agdr_dir)
            num_str = f"{next_num:04d}"
            title_slug = response_data.agdr_title.strip()
            # Clean title slug
            title_slug = "".join(
                c if c.isalnum() or c in ("-", "_") else "-" for c in title_slug
            ).lower()
            title_slug = "-".join(filter(None, title_slug.split("-")))
            if not title_slug:
                title_slug = "decision"

            agdr_filename = f"{num_str}-{title_slug}.md"
            agdr_path = agdr_dir / agdr_filename

            # Format AgDR Header Metadata
            best_score = best_option.get("score", 0.0)
            status = "Accepted" if best_score >= 6.0 else "Proposed"
            today = datetime.date.today().isoformat()

            span_context = trace.get_current_span().get_span_context()
            trace_id = (
                f"{span_context.trace_id:032x}"
                if span_context.is_valid and span_context.trace_id != 0
                else "unknown-trace"
            )
            trigger_issue = draft_path.name

            # Map slug to title header
            title_display = response_data.agdr_title.replace("-", " ").title()

            header = (
                f"# {num_str} - {title_display}\n\n"
                f"* **Status**: {status}\n"
                f"* **Datum**: {today}\n"
                f"* **Entscheidungsträger**: {critic_model_name}\n"
                f"* **Trace-ID**: {trace_id}\n"
                f"* **Trigger-Issue**: {trigger_issue}\n\n"
            )

            full_agdr_content = header + response_data.agdr_content.strip() + "\n"

            try:
                with open(agdr_path, "w", encoding="utf-8") as f:
                    f.write(full_agdr_content)
                logger.info(f"Successfully wrote new AgDR to {agdr_path}")
            except Exception as e:
                raise IOError(f"Failed to write AgDR to {agdr_path}: {e}")

        # 5. Rewrite/update the local draft issue file
        updated_content = response_data.updated_issue_content.strip()
        if updated_content and updated_content != draft_content:
            try:
                # Overwrite with enriched content directly (existence already validated above)
                with open(draft_path, "w", encoding="utf-8") as f:
                    f.write(updated_content + "\n")
                logger.info(f"Successfully updated draft issue at {draft_path}")
            except Exception as e:
                raise IOError(f"Failed to update draft issue at {draft_path}: {e}")
        else:
            logger.info("No modifications to draft issue content.")

        return {
            "prompt_tokens": state.get("prompt_tokens", 0) + prompt_tokens,
            "completion_tokens": state.get("completion_tokens", 0) + completion_tokens,
            "status": "success",
        }
