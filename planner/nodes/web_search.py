import os
import json
import re
import logging
from typing import Dict, Any
from langchain_core.messages import SystemMessage, HumanMessage
from planner.state import RefinementState
from planner.models import ChatOpenRouter
from scripts.telemetry import orchestrator_phase

logger = logging.getLogger("planner.nodes.web_search")


def extract_json_block(text: str) -> str:
    """Helper to extract a JSON block from Markdown output."""
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Fallback to look for array pattern if no markdown block
    match = re.search(r"(\[.*\])", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def web_search_node(state: RefinementState) -> Dict[str, Any]:
    """Executes search via OpenRouter's server-side web search tool."""
    logger.info("Running web_search node...")

    with orchestrator_phase("web_search"):
        queries = state.get("search_queries", [])
        strict_mode = state.get("strict_mode", True)
        allowed_domains = state.get("allowed_domains", [])

        if strict_mode and not allowed_domains:
            raise ValueError(
                "Strict-mode is enabled, but allowed_domains is empty. "
                "At least one source must be defined."
            )

        if not queries:
            logger.info("No search queries generated. Skipping search.")
            return {"search_results": [], "status": "success"}

        # Instantiate OpenRouter client
        model_name = os.getenv("AGENT_MODEL", "google/gemini-2.5-flash")
        model = ChatOpenRouter(model=model_name, temperature=0.0)

        # Build tool definition
        tool_definition = {
            "type": "openrouter:web_search",
            "parameters": {"engine": "auto"},
        }

        # Inject allowed domains/repositories if defined (crucial for ADR-0002 compliance)
        if allowed_domains:
            tool_definition["parameters"]["allowed_domains"] = allowed_domains

        # Bind tool and force the tool choice to guarantee search execution
        llm_with_tools = model.bind_tools(
            [tool_definition], tool_choice={"type": "openrouter:web_search"}
        )

        # Instruct the model to perform the search and return structured output
        system_instruction = (
            "You are a technical researcher. You MUST use the openrouter:web_search tool "
            "to execute a search for the requested queries. Do not try to answer without using the tool.\n\n"
            "After you perform the search and receive the results, synthesize your findings. "
            "At the end of your response, you MUST append a JSON block representing the list of search results you found. "
            "Citations and snippets must be truncated to be concise (max 300 chars per snippet).\n\n"
            "The JSON block must start with ```json and end with ```, and look exactly like this:\n"
            "[\n"
            "  {\n"
            '    "title": "Result Title",\n'
            '    "url": "http://example.com/result",\n'
            '    "snippet": "A brief summary of findings (max 300 chars)"\n'
            "  }\n"
            "]"
        )

        user_message = f"Search Queries: {', '.join(queries)}"
        if allowed_domains:
            user_message += f"\nAllowed Domains/Repositories (Search is strictly restricted to these): {', '.join(allowed_domains)}"

        search_results = []
        prompt_tokens = 0
        completion_tokens = 0
        messages = list(state.get("messages", []))

        try:
            response = llm_with_tools.invoke(
                [
                    SystemMessage(content=system_instruction),
                    HumanMessage(content=user_message),
                ]
            )

            # Save message history
            messages.append(HumanMessage(content=user_message))
            messages.append(response)

            # Parse response metadata
            if response.response_metadata:
                token_usage = response.response_metadata.get("token_usage", {})
                prompt_tokens = token_usage.get("prompt_tokens", 0)
                completion_tokens = token_usage.get("completion_tokens", 0)

            # Extract and parse the JSON block of search results
            json_text = extract_json_block(response.content)
            parsed_results = json.loads(json_text)

            if isinstance(parsed_results, list):
                for item in parsed_results:
                    if isinstance(item, dict) and "url" in item:
                        # Truncate snippet to prevent bloating
                        snippet = item.get("snippet", "")
                        if len(snippet) > 300:
                            snippet = snippet[:297] + "..."
                        search_results.append(
                            {
                                "title": item.get("title", "No Title"),
                                "url": item.get("url"),
                                "snippet": snippet,
                            }
                        )

        except Exception as e:
            logger.error(f"Error executing web search or parsing results: {e}")
            # Empty results fallback, do not crash
            search_results = []

        # Cap final list to max 10 results to respect context window limits
        search_results = search_results[:10]

        return {
            "messages": messages,
            "search_results": search_results,
            "prompt_tokens": state.get("prompt_tokens", 0) + prompt_tokens,
            "completion_tokens": state.get("completion_tokens", 0) + completion_tokens,
            "status": "success",
        }
