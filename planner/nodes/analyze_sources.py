import os
import json
import logging
from typing import Dict, Any
from langchain_core.messages import SystemMessage, HumanMessage
from planner.state import RefinementState
from langchain_openai import ChatOpenAI
from scripts.telemetry import orchestrator_phase

logger = logging.getLogger("planner.nodes.analyze_sources")


def analyze_sources_node(state: RefinementState) -> Dict[str, Any]:
    """Analyzes the draft issue to extract keywords and optionally suggest sources."""
    logger.info("Running analyze_sources node...")

    with orchestrator_phase("analyze_sources"):
        draft_content = state.get("draft_issue_content", "")
        strict_mode = state.get("strict_mode", True)
        allowed_domains = state.get("allowed_domains", [])

        if strict_mode and not allowed_domains:
            raise ValueError(
                "Strict-mode is enabled, but allowed_domains is empty. "
                "At least one source must be defined."
            )

        # Instantiate LangChain ChatOpenAI client configured for OpenRouter
        model_name = (
            os.getenv("REFINE_ANALYZE_SOURCES_MODEL")
            or os.getenv("REFINE_MODEL")
            or os.getenv("AGENT_MODEL")
            or "deepseek/deepseek-v4-pro"
        )
        model = ChatOpenAI(
            model=model_name,
            temperature=0.0,
            openai_api_base="https://openrouter.ai/api/v1",
            openai_api_key=os.getenv("OPENROUTER_API_KEY"),
        )

        # Construct prompt
        system_instruction = (
            "You are an expert technical researcher. Your task is to analyze the draft issue description "
            "and extract a list of search keywords or search queries to find code references, APIs, or architectural patterns.\n"
            "If strict mode is disabled, you can also suggest additional trusted domains or GitHub repositories to search.\n\n"
            "Format your response as a valid JSON object with the following structure:\n"
            "{\n"
            '  "keywords": ["keyword1", "keyword2", ...],\n'
            '  "suggested_sources": ["domain.com", "github.com/org/repo", ...]\n'
            "}"
        )

        user_message = f"Draft Issue Content:\n{draft_content}"

        try:
            # Enable JSON output mode
            model_with_json = model.bind(response_format={"type": "json_object"})
            response = model_with_json.invoke(
                [
                    SystemMessage(content=system_instruction),
                    HumanMessage(content=user_message),
                ]
            )

            result = json.loads(response.content)
            keywords = result.get("keywords", [])
            suggested_sources = result.get("suggested_sources", [])
        except Exception as e:
            logger.error(f"Error parsing LLM response in analyze_sources: {e}")
            keywords = [
                word.strip(".,;:?!") for word in draft_content.split() if len(word) > 5
            ][:5]
            suggested_sources = []
            response = None

        # Whitelist mapping:
        # If strict_mode is True, we completely ignore LLM-suggested sources.
        # If strict_mode is False, we normalize and merge suggested sources.
        base_allowed_domains = list(state.get("allowed_domains", []))
        if not strict_mode:
            for source in suggested_sources:
                source = source.strip().lower()
                # If it's a repository path like "org/repo", prefix with "github.com/"
                if (
                    "/" in source
                    and not source.startswith("github.com")
                    and "." not in source.split("/")[0]
                ):
                    source = f"github.com/{source}"
                if source and source not in base_allowed_domains:
                    base_allowed_domains.append(source)

        # Token usage tracking
        prompt_tokens = 0
        completion_tokens = 0
        if response and response.response_metadata:
            token_usage = response.response_metadata.get("token_usage", {})
            prompt_tokens = token_usage.get("prompt_tokens", 0)
            completion_tokens = token_usage.get("completion_tokens", 0)

        return {
            "keywords": keywords,
            "search_queries": keywords,
            "allowed_domains": base_allowed_domains,
            "prompt_tokens": state.get("prompt_tokens", 0) + prompt_tokens,
            "completion_tokens": state.get("completion_tokens", 0) + completion_tokens,
            "model_name": model_name,
            "status": "success",
        }
