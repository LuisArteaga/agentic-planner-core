import os
import json
import logging
from typing import Dict, Any
from langchain_core.messages import SystemMessage, HumanMessage
from planner.state import RefinementState
from langchain_openai import ChatOpenAI
from planner.nodes.web_search import extract_json_block
from scripts.telemetry import orchestrator_phase
from planner.config import get_model

logger = logging.getLogger("planner.nodes.propose_options")


def propose_options_node(state: RefinementState) -> Dict[str, Any]:
    """Node that proposes technical implementation options based on search results."""
    logger.info("Running propose_options node...")

    with orchestrator_phase("propose_options"):
        draft_content = state.get("draft_issue_content", "")
        search_results = state.get("search_results", [])

        # Instantiate LangChain ChatOpenAI client configured for OpenRouter
        model_name = get_model("propose_options")
        model = ChatOpenAI(
            model=model_name,
            temperature=0.0,
            openai_api_base="https://openrouter.ai/api/v1",
            openai_api_key=os.getenv("OPENROUTER_API_KEY"),
        )

        system_instruction = (
            "You are a Senior Software Architect. Your task is to analyze the draft issue description "
            "and the provided web search results, then propose at least 2-3 distinct technical implementation options.\n\n"
            "CRITICAL INSTRUCTIONS:\n"
            "1. Ground your options in evidence. Prioritize and cite recent scientific studies/preprints (post-2022, e.g. from arXiv, ACM DL) "
            "found in the search results.\n"
            "2. For each option, you MUST anticipate potential criticisms, limitations, YAGNI violations, complexity increases, or conflicts with ADRs.\n"
            "3. Do not introduce unnecessary abstractions. Keep the solutions simple.\n\n"
            "At the end of your response, you MUST append a JSON block representing the list of proposed options. "
            "The JSON block must start with ```json and end with ```, and look exactly like this:\n"
            "[\n"
            "  {\n"
            '    "choice_id": "option_1",\n'
            '    "name": "Short Descriptive Name",\n'
            '    "description": "Detailed explanation. Grounded in [study name/URL]...",\n'
            '    "anticipated_criticism": "Limitations: ..." \n'
            "  }\n"
            "]"
        )

        search_context = ""
        if search_results:
            search_context = "Web Search Results:\n" + "\n".join(
                [
                    f"- Title: {r.get('title')}\n  URL: {r.get('url')}\n  Snippet: {r.get('snippet')}"
                    for r in search_results
                ]
            )
        else:
            search_context = "No search results available."

        user_message = (
            f"Draft Issue Content:\n{draft_content}\n\n"
            f"{search_context}\n\n"
            f"Propose 2-3 distinct technical options in the required JSON format."
        )

        prompt_tokens = 0
        completion_tokens = 0
        messages = list(state.get("messages", []))
        proposed_options = []

        try:
            response = model.invoke(
                [
                    SystemMessage(content=system_instruction),
                    HumanMessage(content=user_message),
                ]
            )

            messages.append(HumanMessage(content=user_message))
            messages.append(response)

            if response.response_metadata:
                token_usage = response.response_metadata.get("token_usage", {})
                prompt_tokens = token_usage.get("prompt_tokens", 0)
                completion_tokens = token_usage.get("completion_tokens", 0)

            # Extract and parse options list
            assert isinstance(response.content, str)
            json_text = extract_json_block(response.content)
            parsed_options = json.loads(json_text)

            if isinstance(parsed_options, list):
                for opt in parsed_options:
                    if isinstance(opt, dict) and "choice_id" in opt and "name" in opt:
                        proposed_options.append(
                            {
                                "choice_id": opt.get("choice_id"),
                                "name": opt.get("name"),
                                "description": opt.get("description", ""),
                                "anticipated_criticism": opt.get(
                                    "anticipated_criticism", ""
                                ),
                            }
                        )

        except Exception as e:
            logger.error(f"Error proposing options or parsing JSON: {e}")
            # Do not crash, keep proposed_options empty, downstream nodes will handle it

        return {
            "messages": messages,
            "proposed_options": proposed_options,
            "prompt_tokens": state.get("prompt_tokens", 0) + prompt_tokens,
            "completion_tokens": state.get("completion_tokens", 0) + completion_tokens,
            "status": "success" if proposed_options else "failed",
        }
