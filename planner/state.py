from typing import TypedDict, List, Dict, Any


class RefinementState(TypedDict, total=False):
    """Isolated state schema for the Refinement Subgraph."""

    # Inputs passed from the master graph
    draft_issue_content: str
    draft_issue_path: str
    strict_mode: bool
    allowed_domains: List[str]
    search_params: Dict[str, Any]

    # Message History for LLM tool invocation & response
    messages: List[Any]

    # Extracted keywords & compiled search queries
    keywords: List[str]
    search_queries: List[str]

    # Extracted search results from ToolMessages
    search_results: List[Dict[str, Any]]

    # Telemetry and Token Tracking
    prompt_tokens: int
    completion_tokens: int
    model_name: str

    # Status track
    status: str  # "success", "failed", "web_search_failed"

    # Durable web_search failure signal (set by the web_search node when the
    # OpenRouter search returns no url_citation annotations or raises). Unlike
    # ``status`` — which downstream nodes overwrite — this field persists for the
    # whole subgraph run so monitoring can distinguish a degraded search.
    web_search_error: str

    # Critic Grading fields
    proposed_options: List[Dict[str, Any]]
    best_option: Dict[str, Any]
    all_grades: List[Dict[str, Any]]


class AgentState(TypedDict, total=False):
    """State schema for the Master Graph."""

    # List of all draft issues to be processed
    draft_issues: List[str]  # Paths or contents of draft issues
    current_issue_index: int

    # Configuration
    strict_mode: bool
    allowed_domains: List[str]
    search_params: Dict[str, Any]

    # Overall status
    status: str
