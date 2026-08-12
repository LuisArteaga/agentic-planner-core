import logging
from typing import Dict, Any, List, Tuple
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from planner.state import RefinementState
from scripts.telemetry import orchestrator_phase
from planner.config import AppConfig, get_llm
from planner.tools.research import fetch_allowed_url
from planner.utils import active_search_results


def _source_keys(result: Dict[str, Any]) -> List[str]:
    from urllib.parse import urlparse

    url = (result.get("url") or "").strip().lower()
    host = (urlparse(url).netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    keys = []
    if url:
        keys.append(url)
    if host:
        keys.append(host)
    return keys


def _is_blacklisted(result: Dict[str, Any], blacklist: List[str]) -> bool:
    if not blacklist:
        return False
    bl = {b.strip().lower() for b in blacklist if b}
    return any(key in bl for key in _source_keys(result))


logger = logging.getLogger("planner.nodes.web_search")

# Cross-query aggregation cap (#57). After running one search per extracted
# query, citations are deduplicated by URL and capped to this many total
# results. This is distinct from OpenRouter's per-request ``max_total_results``
# (which caps cumulative results *within a single request* where the model
# searches multiple times) — see ADR-0013.
MAX_AGGREGATED_RESULTS = 20


def _extract_citations_from_annotations(annotations: Any) -> list[Dict[str, Any]]:
    """Derive structured search results from OpenRouter ``url_citation`` annotations.

    OpenRouter surfaces web search results as ``url_citation`` entries in the
    message ``annotations`` array (see
    https://openrouter.ai/docs/guides/features/server-tools/web-search#parsing-web-search-results).
    Annotations may arrive as plain dicts or pydantic models depending on the
    LangChain/OpenAI SDK version, so both are normalized to dicts here.
    """
    citations: list[Dict[str, Any]] = []
    for ann in annotations or []:
        if hasattr(ann, "model_dump"):
            ann = ann.model_dump()
        if not isinstance(ann, dict):
            continue
        if ann.get("type") != "url_citation":
            continue
        citation = ann.get("url_citation") or {}
        if hasattr(citation, "model_dump"):
            citation = citation.model_dump()
        if not isinstance(citation, dict):
            continue
        url = citation.get("url")
        if not url:
            continue
        title = citation.get("title") or "No Title"
        snippet = citation.get("content") or ""
        if len(snippet) > 300:
            snippet = snippet[:297] + "..."
        citations.append({"title": title, "url": url, "snippet": snippet})
    return citations


def _run_single_query(
    llm_with_tools: Any,
    query: str,
    allowed_domains: List[str],
    messages: List[Any],
) -> Tuple[List[Dict[str, Any]], int, int]:
    """Execute one OpenRouter server-side web search for a single query.

    Returns ``(citations, prompt_tokens, completion_tokens)``. The prose
    synthesis is appended to ``messages`` for downstream/tracing context (note:
    ``propose_options`` grounds on the structured ``search_results`` list, not
    on these messages).
    """
    system_instruction = (
        "You are a technical researcher. You MUST use the openrouter:web_search tool "
        "to execute a search for the requested query. Do not try to answer without using the tool.\n\n"
        "After you perform the search and receive the results, synthesize your findings into a concise "
        "prose summary and cite sources inline. Do not output a JSON block; the structured search "
        "results are captured automatically from the tool's url_citation annotations."
    )

    user_message = f"Search Query: {query}"
    if allowed_domains:
        user_message += (
            f"\nAllowed Domains/Repositories "
            f"(Search is strictly restricted to these): {', '.join(allowed_domains)}"
        )

    response: AIMessage = llm_with_tools.invoke(
        [
            SystemMessage(content=system_instruction),
            HumanMessage(content=user_message),
        ]
    )

    messages.append(HumanMessage(content=user_message))
    messages.append(response)

    prompt_tokens = 0
    completion_tokens = 0
    if response.response_metadata:
        token_usage = response.response_metadata.get("token_usage", {})
        prompt_tokens = token_usage.get("prompt_tokens", 0)
        completion_tokens = token_usage.get("completion_tokens", 0)

    annotations = getattr(response, "additional_kwargs", {}).get("annotations", [])
    citations = _extract_citations_from_annotations(annotations)

    return citations, prompt_tokens, completion_tokens


def web_search_node(state: RefinementState) -> Dict[str, Any]:
    """Executes one OpenRouter server-side web search per extracted query (#57).

    Citations are accumulated across all queries, deduplicated by URL, and
    capped to ``MAX_AGGREGATED_RESULTS``. A per-query failure (e.g. a transient
    OpenRouter 504) is isolated: it does not discard earlier queries' results
    (no silent drop, #56 spirit).
    """
    logger.info("Running web_search node...")

    with orchestrator_phase("web_search"):
        queries = state.get("search_queries", [])
        strict_mode = state.get("strict_mode", True)
        allowed_domains = state.get("allowed_domains", [])

        # Zero-Trust self-healing retry re-entry (ADR-0020): on a security
        # retry the graph re-enters this node to FILTER the accumulated results
        # against the blacklist — it does NOT re-fetch (re-searching the same
        # queries would return the same indexed source). The cleaned view is
        # written to ``sanitized_search_results``; ``search_results`` (reducer)
        # is left untouched.
        if int(state.get("security_retries", 0) or 0) > 0:
            blacklist = state.get("blacklisted_sources", []) or []
            base = active_search_results(state)
            cleaned = [r for r in base if not _is_blacklisted(r, blacklist)]
            logger.info(
                f"Security retry: filtered {len(base)} -> {len(cleaned)} results "
                f"(blacklist={len(blacklist)}). No re-fetch."
            )
            return {
                "search_results": [],
                "sanitized_search_results": cleaned,
                "status": "success",
                "web_search_error": "",
            }

        if strict_mode and not allowed_domains:
            raise ValueError(
                "Strict-mode is enabled, but allowed_domains is empty. "
                "At least one source must be defined."
            )

        if not queries:
            logger.info("No search queries generated. Skipping search.")
            return {"search_results": [], "status": "success"}

        model = get_llm("web_search")

        # Build tool definition dynamically (params are identical for every
        # query, so the bound runnable is built once and reused per query).
        search_params = state.get("search_params") or {}
        tool_parameters: Dict[str, Any] = {
            "engine": search_params.get("engine", "auto")
        }
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

        llm_with_tools = model.bind(
            tools=[tool_definition],
            tool_choice={"type": "openrouter:web_search"},
        )

        # Pre-fetch configured direct URLs (strict-mode-bounded).
        config = AppConfig()
        direct_results: List[Dict[str, Any]] = []
        if config.sources.urls:
            logger.info(
                f"Pre-fetching {len(config.sources.urls)} direct URLs from sources configuration..."
            )
            for url in config.sources.urls:
                if url:
                    res_dict = fetch_allowed_url(config, url)
                    if res_dict:
                        direct_results.append(res_dict)

        messages = list(state.get("messages", []))
        total_prompt_tokens = 0
        total_completion_tokens = 0
        per_query_errors: List[str] = []
        per_query_citations: List[Dict[str, Any]] = []

        # Fan out: one search call per query, accumulating citations.
        for query in queries:
            try:
                citations, ptoks, ctoks = _run_single_query(
                    llm_with_tools, query, allowed_domains, messages
                )
                total_prompt_tokens += ptoks
                total_completion_tokens += ctoks
                if not citations:
                    logger.warning(
                        f"Query '{query}' returned no url_citation annotations."
                    )
                    per_query_errors.append(
                        f"query '{query}': no url_citation annotations"
                    )
                else:
                    per_query_citations.extend(citations)
            except Exception as e:
                logger.error(
                    f"Error executing web search for query '{query}': {e}",
                    exc_info=True,
                )
                per_query_errors.append(f"query '{query}': {e}")

        # Deduplicate by URL (case-insensitive), direct results first, then cap.
        seen_urls: set[str] = set()
        aggregated: List[Dict[str, Any]] = []

        def _add_unseen(item: Dict[str, Any]) -> None:
            url = (item.get("url") or "").strip().lower()
            if not url or url in seen_urls:
                return
            seen_urls.add(url)
            aggregated.append(item)

        for item in direct_results:
            _add_unseen(item)
        for item in per_query_citations:
            _add_unseen(item)

        search_results = aggregated[:MAX_AGGREGATED_RESULTS]

        # Honest status: a single non-empty aggregated set is a success even if
        # some queries failed/returned nothing. Total failure is explicit.
        if search_results:
            status = "success"
            web_search_error = "; ".join(per_query_errors) if per_query_errors else ""
        else:
            status = "web_search_failed"
            web_search_error = (
                "; ".join(per_query_errors)
                or "No url_citation annotations present in any OpenRouter response."
            )

        if per_query_errors:
            logger.warning(
                f"web_search completed with {len(per_query_errors)} per-query issue(s)."
            )

        return {
            "messages": messages,
            "search_results": search_results,
            "prompt_tokens": state.get("prompt_tokens", 0) + total_prompt_tokens,
            "completion_tokens": state.get("completion_tokens", 0)
            + total_completion_tokens,
            "status": status,
            "web_search_error": web_search_error,
        }
