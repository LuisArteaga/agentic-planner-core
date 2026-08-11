import os
import logging
import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage
from opentelemetry import trace
from planner.state import RefinementState
from scripts.telemetry import orchestrator_phase
from planner.nodes.evaluate_grade import load_adrs
from planner.config import get_llm, resolve_model_config


logger = logging.getLogger("planner.nodes.apply_decision")


def _extract_finish_reason(raw_msg: Any) -> Optional[str]:
    """Best-effort extraction of the provider ``finish_reason`` from a raw AIMessage.

    With ``include_raw=True``, LangChain returns the underlying ``AIMessage`` as
    ``raw``. OpenRouter/OpenAI-compatible providers surface ``finish_reason``
    (``stop`` | ``length`` | ``tool_calls`` | ...) in ``response_metadata``.
    """
    if raw_msg is None:
        return None
    meta = getattr(raw_msg, "response_metadata", None) or {}
    if isinstance(meta, dict):
        return meta.get("finish_reason")
    return None


class AgDROption(BaseModel):
    """Pydantic schema representing a single evaluated option for the AgDR."""

    name: str = Field(description="The name of the implementation option.")
    description: str = Field(
        description="A short explanation of how the option works and its tradeoffs."
    )
    score: float = Field(description="The score assigned by the Critic (0.0 to 10.0).")
    checks_passed: int = Field(
        description="The number of atomic criteria checks passed (0 to 10)."
    )


class AgDRConsequences(BaseModel):
    """Pydantic schema for positive and negative consequences of the decision."""

    positive: List[str] = Field(
        default_factory=list, description="List of pros/advantages."
    )
    negative: List[str] = Field(default_factory=list, description="List of cons/risks.")


# Implementation-ready sections the refinement must inject into every published
# issue so the downstream coding agent can implement without re-researching or
# re-deciding architecture. Inspired by GitHub Spec Kit's plan/tasks separation
# (Constitution -> Specify -> Plan -> Tasks -> implementation by a coding agent).
# The planner still emits SPECS ONLY (no code, no branches in target repos) per
# ADR-0001 and PRD AC1; these sections front-load the engineering depth.
IMPLEMENTATION_READY_SECTIONS: List[tuple[str, str]] = [
    (
        "## Solution approach",
        "The chosen implementation approach: its name, a one-paragraph rationale grounded "
        "in the Critic grading scores, and a one-line note on why the highest-scoring "
        "alternative was rejected (with its score). Link the AgDR if one was created.",
    ),
    (
        "## Implementation plan",
        "An ordered, file-targeted list of concrete steps. Each step names the exact target "
        "file path(s) to create or modify (relative to the repository root) and the precise "
        "change to make. This is the path the coding agent follows without re-deciding.",
    ),
    (
        "## Verified patterns & references",
        "Syntax-verified code patterns, library usages, or API shapes drawn from the web "
        "search results, each with a citation URL. Describe the canonical pattern to follow, "
        "NOT the full final implementation.",
    ),
    (
        "## Resolved ambiguities",
        "Each ambiguity encountered during refinement, paired with its resolution and the "
        "industry standard or rationale cited, so the coding agent does not re-litigate "
        "decisions already made.",
    ),
]

_IMPLEMENTATION_READY_SECTIONS_DESC = "\n".join(
    f"- {header}: {desc}" for header, desc in IMPLEMENTATION_READY_SECTIONS
)

# Full description for the `updated_issue_content` Pydantic field.
UPDATED_ISSUE_CONTENT_DESC = (
    "Complete rewritten draft issue markdown. Preserve and enrich ALL original section headers. "
    "Additionally ENSURE the following implementation-ready sections are present (insert them if "
    "missing) and populate each with concrete, file-targeted detail grounded in the search results "
    "and the chosen option:\n"
    + _IMPLEMENTATION_READY_SECTIONS_DESC
    + "\nDo NOT write final code - describe canonical patterns and target locations only. "
    "If refinement yielded no new findings, keep this identical to the original content."
)


class ApplyDecisionOutput(BaseModel):
    """Pydantic model for structured decision output from LLM."""

    requires_agdr: bool = Field(
        description="Whether a new Agent Decision Record (AgDR) is required."
    )
    agdr_title: str = Field(
        description="A short kebab-case title slug for the new AgDR (e.g., 'use-sqlite-cache'). Empty if requires_agdr is false."
    )
    y_statement: str = Field(
        description="A single-sentence summary of the decision following the pattern: 'In the context of [situation], facing [concern], we decided [decision] to achieve [result].' Empty if requires_agdr is false."
    )

    # Structured AgDR content fields (to ensure Options-Matrix and Decision Rationale are present)
    context_and_problem: str = Field(
        description="Description of the context, the concrete problem, and why this decision is hard to reverse. Empty if requires_agdr is false."
    )
    drivers: List[str] = Field(
        default_factory=list,
        description="List of key decision factors/drivers (e.g. scalability, simplicity). Empty if requires_agdr is false.",
    )
    options_considered: List[AgDROption] = Field(
        default_factory=list,
        description="The options that were evaluated, detailing their score and description. Empty if requires_agdr is false.",
    )
    decision_rationale: str = Field(
        description="Detailed explanation of why the chosen option was selected and how it addresses the drivers. Empty if requires_agdr is false."
    )
    consequences: AgDRConsequences = Field(
        default_factory=AgDRConsequences,
        description="The anticipated positive and negative consequences of this decision. Empty if requires_agdr is false.",
    )
    references: List[str] = Field(
        default_factory=list,
        description="Citations, URLs, standard specs, or existing ADRs/AgDRs referenced. Empty if requires_agdr is false.",
    )

    updated_issue_content: str = Field(description=UPDATED_ISSUE_CONTENT_DESC)


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

        workspace_dir = Path(os.environ.get("GITHUB_WORKSPACE", os.getcwd())).resolve()

        from planner.utils import validate_draft_path

        draft_path = validate_draft_path(draft_path_str, workspace_dir)

        if not draft_path.exists():
            raise FileNotFoundError(f"Draft issue file does not exist: {draft_path}")

        # 1. Load existing ADRs and AgDRs to provide context to the LLM
        existing_adrs = load_adrs(str(workspace_dir / "docs" / "adr"))
        existing_agdrs = load_adrs(str(workspace_dir / "docs" / "agdr"))

        combined_decisions = ""
        if existing_adrs:
            combined_decisions += f"Existing human ADRs:\n{existing_adrs}\n\n"
        if existing_agdrs:
            combined_decisions += f"Existing agent AgDRs:\n{existing_agdrs}\n\n"

        # 2. Configure model using get_llm with an explicit, configurable
        # max_tokens so the large implementation-ready payload is not truncated
        # at the provider default (#56). ``strict=True`` forces schema adherence
        # via function calling (supported by OpenRouter, see ADR-0003).
        base_max_tokens = resolve_model_config("apply_decision")["max_tokens"] or 16384
        current_max_tokens = base_max_tokens
        model = get_llm("apply_decision")

        structured_model = model.with_structured_output(
            ApplyDecisionOutput, include_raw=True, strict=True
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
            "2. If requires_agdr is true, you MUST fully populate the structured AgDR fields:\n"
            "   - 'agdr_title': a short kebab-case title slug (e.g. 'use-sqlite-cache')\n"
            "   - 'y_statement': MUST follow the pattern: 'In the context of [situation], facing [concern], we decided [decision] to achieve [result].'\n"
            "   - 'context_and_problem': Description of context and why it is hard to reverse.\n"
            "   - 'drivers': Key factors/drivers.\n"
            "   - 'options_considered': Fully list the alternatives, including names, descriptions, scores, and checks passed.\n"
            "   - 'decision_rationale': Why the option was chosen and how it satisfies the drivers.\n"
            "   - 'consequences': Positive and negative consequences.\n"
            "   - 'references': Inspiration and web-search/code references.\n"
            "3. Rewrite the draft issue into an IMPLEMENTATION-READY spec. Preserve and enrich all "
            "original section headers (e.g. ## What to build, ## Scope, ## Constraints, ## Edge cases, "
            "## Cross-cutting concerns, ## Acceptance criteria, ## Blocked by) with:\n"
            "   - Research findings (citing search results and URLs).\n"
            "   - Grading reasons and scores of the evaluated options.\n"
            "   - Clear references or links to any existing ADRs/AgDRs or the newly created AgDR.\n"
            "   ADDITIONALLY ENSURE the following implementation-ready sections are present (insert them "
            "if missing) and fill each with concrete, file-targeted detail grounded in the search results "
            "and the chosen option. Do NOT write final code - describe canonical patterns and target "
            "locations only:\n"
            + "\n".join(
                f"   - {header}: {desc}"
                for header, desc in IMPLEMENTATION_READY_SECTIONS
            )
            + "\n"
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

        # Execute LLM call with retry loop (up to 3 times).
        # On a parse failure we distinguish truncation (finish_reason == "length")
        # from malformed JSON: truncation bumps max_tokens and rebuilds the model;
        # malformed JSON re-prompts with the parsing error (#56).
        for attempt in range(1, 4):
            try:
                logger.info(f"Structured decision attempt {attempt}/3...")
                if attempt == 1:
                    content = user_message
                else:
                    content = (
                        f"{user_message}\n\n"
                        f"WARNING: Your previous attempt failed with error:\n"
                        f"{last_error}\n"
                        f"Please correct the error and output valid JSON matching the schema."
                    )
                response = structured_model.invoke(
                    [
                        SystemMessage(content=system_instruction),
                        HumanMessage(content=content),
                    ]
                )

                if response and isinstance(response, dict):
                    parsed_val = response.get("parsed")
                    raw_msg = response.get("raw")
                    parsing_error = response.get("parsing_error")
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

                    # Parse failure: classify by finish_reason and log it.
                    finish_reason = _extract_finish_reason(raw_msg)
                    last_error = (
                        str(parsing_error)
                        if parsing_error
                        else f"parsed value was not ApplyDecisionOutput "
                        f"(finish_reason={finish_reason})"
                    )
                    if finish_reason == "length":
                        logger.warning(
                            f"Attempt {attempt} truncated (finish_reason=length); "
                            f"retrying with larger max_tokens."
                        )
                        current_max_tokens = current_max_tokens * 2
                        model = get_llm(
                            "apply_decision",
                            max_tokens_override=current_max_tokens,
                        )
                        structured_model = model.with_structured_output(
                            ApplyDecisionOutput, include_raw=True, strict=True
                        )
                    else:
                        logger.warning(
                            f"Attempt {attempt} malformed output "
                            f"(finish_reason={finish_reason}): {last_error}"
                        )
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
            agdr_path = (agdr_dir / agdr_filename).resolve()

            # Validate path containment to prevent path traversal
            try:
                agdr_path.relative_to(workspace_dir)
            except ValueError:
                raise ValueError(
                    f"Path traversal detected: AgDR path {agdr_path} is outside GITHUB_WORKSPACE {workspace_dir}"
                )

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
                f"* **Trigger-Issue**: {trigger_issue}\n"
                f"* **Y-Statement**: {response_data.y_statement.strip()}\n\n"
            )

            # Stitch the structured AgDR markdown sections together
            drivers_list = "\n".join(
                f"* {d.strip()}" for d in response_data.drivers if d.strip()
            )
            pros_list = "\n".join(
                f"* {p.strip()}"
                for p in response_data.consequences.positive
                if p.strip()
            )
            cons_list = "\n".join(
                f"* {c.strip()}"
                for c in response_data.consequences.negative
                if c.strip()
            )
            refs_list = "\n".join(
                f"* {r.strip()}" for r in response_data.references if r.strip()
            )

            # Generate the Options-Matrix markdown table
            options_matrix = (
                "| Option | Score | Checks Passed | Description |\n"
                "| :--- | :--- | :--- | :--- |\n"
            )
            for opt in response_data.options_considered:
                options_matrix += f"| {opt.name} | {opt.score}/10.0 | {opt.checks_passed}/10 | {opt.description} |\n"

            agdr_body = (
                f"## Kontext und Problemstellung\n{response_data.context_and_problem.strip()}\n\n"
                f"## Entscheidungsfaktoren (Drivers)\n{drivers_list if drivers_list else '* None'}\n\n"
                f"## Betrachtete Optionen\n{options_matrix}\n"
                f"## Entscheidung\n{response_data.decision_rationale.strip()}\n\n"
                f"### Konsequenzen\n"
                f"* **Positiv**:\n{pros_list if pros_list else '* None'}\n"
                f"* **Negativ**:\n{cons_list if cons_list else '* None'}\n\n"
                f"## Inspiration & Referenzen\n{refs_list if refs_list else '* None'}\n"
            )

            full_agdr_content = header + agdr_body

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
