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

    # Zero-Error-Tolerance AddOn (ADR-0019). ``zero_tolerance`` enables the
    # gates; ``zero_tolerance_config`` carries the deterministic thresholds.
    zero_tolerance: bool
    zero_tolerance_config: Dict[str, Any]
    # Original structural signature (computed before refinement) used by the
    # cascade collision gate to detect structural changes.
    original_draft_signature: str
    # Resolved by ``detect_structural_change_node`` after ``apply_decision``.
    trivial: bool
    structurally_changed: bool
    # Populated by the Intent Gate node.
    intent_line: str

    # Zero-Trust Prompt-Injection Defense (ADR-0020). ``security_config``
    # carries the per-run security knobs; ``security_audit`` is enabled when
    # ``audit_level != "off"``. ``sanitized_search_results`` is ``None`` until
    # the audit (or a retry re-entry of ``web_search``) produces a cleaned view;
    # downstream nodes read it via ``active_search_results`` so an offline
    # fallback (empty list) or a blacklisted-source filter takes effect without
    # disturbing the accumulated ``search_results`` reducer.
    security_config: Dict[str, Any]
    sanitized_search_results: Any  # None | List[Dict[str, Any]]
    security_retries: int
    blacklisted_sources: Annotated[List[str], operator.add]
    security_audit_result: Dict[str, Any]
    security_route: str  # "apply" | "retry"
    offline_refinement: bool
    security_findings: Annotated[List[Dict[str, Any]], operator.add]
    require_approval: bool


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

    # Zero-Error-Tolerance AddOn (ADR-0019).
    zero_tolerance: bool
    zero_tolerance_config: Dict[str, Any]
    # filename -> blocker filenames, parsed once by the batch gate.
    dependency_map: Dict[str, List[str]]
    # Drafts whose structure changed during refinement (cascade trigger).
    changed_drafts: Annotated[List[str], operator.add]
    # Downstream drafts marked stale by the cascade collision gate.
    stale_drafts: Annotated[List[str], operator.add]

    # Zero-Trust Prompt-Injection Defense (ADR-0020) — accumulated across the
    # master loop so a single per-run security report can be written.
    security_config: Dict[str, Any]
    security_findings: Annotated[List[Dict[str, Any]], operator.add]
    blacklisted_sources: Annotated[List[str], operator.add]
    offline_refinement: bool
    require_approval: bool
