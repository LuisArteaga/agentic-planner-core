import operator
from typing import Annotated, TypedDict, List, Dict, Any


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

    # Extracted search results from ToolMessages.
    # Accumulation reducer: node returns append (never overwrite) so a future
    # multi-query web_search refactor (#57) cannot silently drop earlier results.
    search_results: Annotated[List[Dict[str, Any]], operator.add]

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

    # Critic Grading fields.
    # ``proposed_options`` and ``all_grades`` use accumulation reducers so node
    # returns append rather than overwrite, closing the silent-drop class (#56).
    proposed_options: Annotated[List[Dict[str, Any]], operator.add]
    best_option: Dict[str, Any]
    all_grades: Annotated[List[Dict[str, Any]], operator.add]


class AgentState(TypedDict, total=False):
    """State schema for the Master Graph."""

    # List of all draft issues to be processed
    draft_issues: List[str]  # Paths or contents of draft issues
    current_issue_index: int

    # Configuration
    strict_mode: bool
    allowed_domains: List[str]
    search_params: Dict[str, Any]

    # Overall status (last-iteration value; the terminal batch status is computed
    # from ``succeeded_drafts`` / ``failed_drafts`` in the CLI entrypoint).
    status: str

    # Per-draft outcomes accumulated across master-loop iterations via reducers.
    # A single overwriteable ``status`` previously hid mid-loop failures (#56);
    # these lists make partial runs honest and drive the terminal exit code.
    succeeded_drafts: Annotated[List[str], operator.add]
    failed_drafts: Annotated[List[str], operator.add]
