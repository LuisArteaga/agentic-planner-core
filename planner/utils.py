import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse


def active_search_results(state: Any) -> List[Dict[str, Any]]:
    """Return the search results a downstream node should reason over.

    The Zero-Trust security audit (ADR-0020) may produce a cleaned view
    (``sanitized_search_results``) that drops blacklisted sources, or an empty
    list when the subgraph fell back to offline refinement. Until the audit
    runs, that field is ``None`` and callers fall back to the accumulated
    ``search_results`` list. Centralizing this here keeps the
    ``search_results`` accumulation reducer (ADR-0013) untouched while letting
    the security filtering/offline path take effect everywhere.
    """
    sanitized = state.get("sanitized_search_results")
    if sanitized is not None:
        return sanitized
    return state.get("search_results", []) or []


def domain_of(url: str) -> str:
    """Lowercased host of ``url`` (strips a leading ``www.``). Empty on failure.

    Shared source-keying helper used by the security audit and the web_search
    retry filter (ADR-0020) so both blacklist against the same normalized
    domain representation — preventing drift between two divergent
    implementations.
    """
    try:
        host = (urlparse(url).netloc or "").lower()
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def source_keys(result: Dict[str, Any]) -> List[str]:
    """Lowercased URL + domain keys for a search result, for blacklist matching.

    Shared by ``security_audit`` and ``web_search`` (ADR-0020) so both nodes
    blacklist the same set of keys for a given source.
    """
    url = (result.get("url") or "").strip().lower()
    domain = domain_of(url)
    keys: List[str] = []
    if url:
        keys.append(url)
    if domain:
        keys.append(domain)
    return keys


def is_blacklisted(result: Dict[str, Any], blacklist: List[str]) -> bool:
    """True iff any source key of ``result`` appears in ``blacklist``.

    Shared by ``security_audit`` and ``web_search`` (ADR-0020).
    """
    if not blacklist:
        return False
    bl = {b.strip().lower() for b in blacklist if b}
    return any(key in bl for key in source_keys(result))


def extract_json_block(text: str) -> str:
    """Extract a JSON block from Markdown output.

    Looks for a fenced ```json block first, then falls back to any array
    pattern, finally returning the stripped text. Shared by nodes that parse
    model-emitted structured output (e.g. ``propose_options``).
    """
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    match = re.search(r"(\[.*\])", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def extract_finish_reason(raw_msg: Any) -> Optional[str]:
    """Best-effort extraction of the provider ``finish_reason`` from a raw AIMessage.

    With ``include_raw=True``, LangChain returns the underlying ``AIMessage`` as
    ``raw``. OpenRouter/OpenAI-compatible providers surface ``finish_reason``
    (``stop`` | ``length`` | ``tool_calls`` | ...) in ``response_metadata``.
    Shared by the structured-output retry loops of ``apply_decision`` and
    ``evaluate_grade`` so truncation (``length``) can be distinguished from
    malformed JSON (#56).
    """
    if raw_msg is None:
        return None
    meta = getattr(raw_msg, "response_metadata", None) or {}
    if isinstance(meta, dict):
        return meta.get("finish_reason")
    return None


def validate_draft_path(filepath: str, workspace_dir: Path) -> Path:
    """Validates that the draft issue path does not attempt path traversal.
    Allows paths inside the GITHUB_WORKSPACE or the central planner drafts directory.
    """
    draft_path = Path(filepath).resolve()

    # Locate central drafts directory in the planner core repository
    planner_root = Path(__file__).resolve().parents[1]
    drafts_base = (planner_root / ".planner" / "drafts").resolve()

    in_drafts = False
    try:
        draft_path.relative_to(drafts_base)
        in_drafts = True
    except ValueError:
        pass

    in_workspace = False
    try:
        draft_path.relative_to(workspace_dir)
        in_workspace = True
    except ValueError:
        pass

    if not (in_drafts or in_workspace):
        raise ValueError(
            f"Path traversal detected: draft issue path {draft_path} is outside GITHUB_WORKSPACE {workspace_dir} "
            f"and planner drafts directory {drafts_base}"
        )

    return draft_path
