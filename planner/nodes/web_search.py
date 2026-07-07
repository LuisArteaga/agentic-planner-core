import json
import re
import logging
from typing import Dict, Any
from langchain_core.messages import SystemMessage, HumanMessage
from planner.state import RefinementState
from scripts.telemetry import orchestrator_phase
from planner.config import AppConfig, get_llm
from planner.tools.research import fetch_allowed_url


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

        # Instantiate LangChain client configured for OpenRouter using get_llm
        model = get_llm("web_search")

        # Build tool definition dynamically
        search_params = state.get("search_params") or {}
        tool_parameters = {"engine": search_params.get("engine", "auto")}
        if search_params.get("search_context_size"):
            tool_parameters["search_context_size"] = search_params[
                "search_context_size"
            ]
        if search_params.get("max_results"):
            tool_parameters["max_results"] = search_params["max_results"]
        if search_params.get("max_total_results"):
            tool_parameters["max_total_results"] = search_params["max_total_results"]
        if allowed_domains:
            tool_parameters["allowed_domains"] = allowed_domains
        if search_params.get("excluded_domains"):
            tool_parameters["excluded_domains"] = search_params["excluded_domains"]

        tool_definition: dict[str, Any] = {
            "type": "openrouter:web_search",
            "parameters": tool_parameters,
        }

        # Bind tool and force the tool choice to guarantee search execution using direct bind
        llm_with_tools = model.bind(
            tools=[tool_definition],
            tool_choice={"type": "openrouter:web_search"},
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

        config = AppConfig()
        direct_results = []
        if config.sources.urls:
            logger.info(
                f"Pre-fetching {len(config.sources.urls)} direct URLs from sources configuration..."
            )
            for url in config.sources.urls:
                if url:
                    res_dict = fetch_allowed_url(config, url)
                    if res_dict:
                        direct_results.append(res_dict)

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
            text_content = ""
            if isinstance(response.content, str):
                text_content = response.content
            elif isinstance(response.content, list):
                for block in response.content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_content += block.get("text", "")
                    elif isinstance(block, str):
                        text_content += block
            json_text = extract_json_block(text_content)
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

        # Combine direct results and search engine results, then cap to max 10
        search_results = direct_results + search_results
        search_results = search_results[:10]

        return {
            "messages": messages,
            "search_results": search_results,
            "prompt_tokens": state.get("prompt_tokens", 0) + prompt_tokens,
            "completion_tokens": state.get("completion_tokens", 0) + completion_tokens,
            "status": "success",
        }
