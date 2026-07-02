from typing import TypedDict, List, Dict, Any


class RefinementState(TypedDict):
    """Isolated state schema for the Refinement Subgraph."""

    # Inputs passed from the master graph
    draft_issue_content: str
    strict_mode: bool
    allowed_domains: List[str]

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
    status: str  # "success", "failed"


class AgentState(TypedDict):
    """State schema for the Master Graph."""

    # List of all draft issues to be processed
    draft_issues: List[str]  # Paths or contents of draft issues
    current_issue_index: int

    # Configuration
    strict_mode: bool
    allowed_domains: List[str]

    # Overall status
    status: str
