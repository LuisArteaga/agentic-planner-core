import logging
from pathlib import Path
from langgraph.graph import StateGraph, END
from planner.state import AgentState, RefinementState
from planner.nodes.analyze_sources import analyze_sources_node
from planner.nodes.web_search import web_search_node
from planner.nodes.propose_options import propose_options_node
from planner.nodes.evaluate_grade import evaluate_grade_node
from planner.nodes.security_audit import route_after_audit, security_audit_node
from planner.nodes.apply_decision import apply_decision_node
from planner.nodes.publish_issue import publish_issue_node
from planner.zero_tolerance.gate import (
    detect_structural_change_node,
    route_after_decision,
    run_cascade_pass,
    threshold_check_node,
)
from planner.zero_tolerance.intent_gate import intent_gate_node
from planner.zero_tolerance.linters import structural_signature
from planner.zero_tolerance.models import ZeroToleranceViolation
from planner.zero_tolerance.planning_judge import planning_judge_node

logger = logging.getLogger("planner.refine_graph")

# Define and compile the Refinement Subgraph
subgraph_workflow = StateGraph(RefinementState)
subgraph_workflow.add_node("analyze_sources", analyze_sources_node)
subgraph_workflow.add_node("web_search", web_search_node)
subgraph_workflow.add_node("propose_options", propose_options_node)
subgraph_workflow.add_node("evaluate_grade", evaluate_grade_node)
subgraph_workflow.add_node("security_audit", security_audit_node)
subgraph_workflow.add_node("apply_decision", apply_decision_node)
subgraph_workflow.add_node("detect_structural_change", detect_structural_change_node)
subgraph_workflow.add_node("threshold_check", threshold_check_node)
subgraph_workflow.add_node("intent_gate", intent_gate_node)
subgraph_workflow.add_node("planning_judge", planning_judge_node)
subgraph_workflow.add_node("publish_issue", publish_issue_node)

subgraph_workflow.set_entry_point("analyze_sources")
subgraph_workflow.add_edge("analyze_sources", "web_search")
subgraph_workflow.add_edge("web_search", "propose_options")
subgraph_workflow.add_edge("propose_options", "evaluate_grade")
# Zero-Trust prompt-injection defense (ADR-0020): audit after grading, before
# the decision. On detection the graph re-enters web_search (filter-only) to
# drop blacklisted sources; on clean/offline it proceeds to apply_decision.
subgraph_workflow.add_edge("evaluate_grade", "security_audit")
subgraph_workflow.add_conditional_edges(
    "security_audit",
    route_after_audit,
    {
        "retry": "web_search",
        "apply": "apply_decision",
    },
)
# After apply_decision, always detect structural change (cheap, deterministic),
# then route based on zero-tolerance + triviality flags.
subgraph_workflow.add_edge("apply_decision", "detect_structural_change")
subgraph_workflow.add_conditional_edges(
    "detect_structural_change",
    route_after_decision,
    {
        "threshold_check": "threshold_check",
        "publish_issue": "publish_issue",
    },
)
subgraph_workflow.add_edge("threshold_check", "intent_gate")
subgraph_workflow.add_edge("intent_gate", "planning_judge")
subgraph_workflow.add_edge("planning_judge", "publish_issue")
subgraph_workflow.add_edge("publish_issue", END)

refine_subgraph = subgraph_workflow.compile()


# Define the Master Graph
def run_refinement_subgraph_node(state: AgentState) -> dict:
    """Master node that runs the Refinement Subgraph for the current draft issue."""
    idx = state.get("current_issue_index", 0)
    draft_issues = state.get("draft_issues", [])

    if idx >= len(draft_issues):
        return {}

    draft_path = Path(draft_issues[idx])
    if not draft_path.exists():
        raise FileNotFoundError(f"Draft issue file not found: {draft_path}")

    with open(draft_path, "r", encoding="utf-8") as f:
        draft_content = f.read()

    zero_tolerance = state.get("zero_tolerance", False)
    zt_config = state.get("zero_tolerance_config", {}) or {}

    # Zero-Trust prompt-injection defense (ADR-0020) config + HITL flag are
    # passed straight through from the master state.
    security_config = state.get("security_config", {}) or {}
    require_approval = bool(state.get("require_approval", False))

    # Cascade collision gate: skip drafts already marked stale by an earlier
    # iteration's structural change (zero-tolerance mode only). The draft stays
    # on disk for a human-driven rerun.
    if zero_tolerance:
        stale_drafts = state.get("stale_drafts", []) or []
        if (
            draft_path.name in stale_drafts
            or (draft_path.with_suffix(".md.stale")).exists()
        ):
            logger.info(
                f"Skipping stale draft {draft_path.name} (upstream structural "
                f"change). Left on disk for rerun."
            )
            return {
                "current_issue_index": idx + 1,
                "failed_drafts": [str(draft_path)],
            }

    subgraph_input: RefinementState = {
        "draft_issue_content": draft_content,
        "draft_issue_path": str(draft_path),
        "strict_mode": state.get("strict_mode", True),
        "allowed_domains": state.get("allowed_domains", []),
        "search_params": state.get("search_params", {}),
        "messages": [],
        "keywords": [],
        "search_queries": [],
        "search_results": [],
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "model_name": "",
        "status": "idle",
        "web_search_error": "",
        "proposed_options": [],
        "best_option": {},
        "all_grades": [],
        "zero_tolerance": zero_tolerance,
        "zero_tolerance_config": zt_config,
        "original_draft_signature": structural_signature(draft_content),
        "trivial": False,
        "structurally_changed": False,
        "intent_line": "",
        "security_config": security_config,
        "require_approval": require_approval,
        "sanitized_search_results": None,
        "security_retries": 0,
        "blacklisted_sources": [],
        "security_audit_result": {},
        "security_route": "apply",
        "offline_refinement": False,
        "security_findings": [],
    }

    # Execute the subgraph. Per ADR-0005, a single draft failure is isolated:
    # it is recorded in ``failed_drafts`` (the draft stays on disk for a rerun)
    # and the batch continues. The terminal batch status is derived from these
    # accumulated lists in the CLI entrypoint rather than from an overwriteable
    # ``status`` field, which previously hid mid-loop failures (#56).
    #
    # Zero-tolerance violations are the exception (ADR-0019): they HALT the
    # entire batch immediately (HITL) instead of being isolated per-draft.
    draft_path_str = str(draft_path)
    try:
        subgraph_result = refine_subgraph.invoke(subgraph_input)
        result: dict = {
            "current_issue_index": idx + 1,
            "succeeded_drafts": [draft_path_str],
            "failed_drafts": [],
        }

        # Cascade collision gate (zero-tolerance only): if the issue was
        # structurally changed during refinement, mark its downstream dependents
        # stale so they are skipped in subsequent iterations of this run.
        if zero_tolerance and subgraph_result.get("structurally_changed"):
            dep_map = state.get("dependency_map", {}) or {}
            remaining = [
                p for i, p in enumerate(draft_issues) if i > idx and Path(p).exists()
            ]
            stale = run_cascade_pass(remaining, [draft_path.name], dep_map)
            if stale:
                result["stale_drafts"] = [Path(s).name for s in stale]
            result["changed_drafts"] = [draft_path.name]

        # Lift Zero-Trust security findings/blacklist/offline into the master
        # state so a single per-run security report can be written (ADR-0020).
        sec_findings = subgraph_result.get("security_findings", []) or []
        sec_blacklist = subgraph_result.get("blacklisted_sources", []) or []
        if sec_findings:
            result["security_findings"] = sec_findings
        if sec_blacklist:
            result["blacklisted_sources"] = sec_blacklist
        if subgraph_result.get("offline_refinement"):
            result["offline_refinement"] = True
        return result
    except ZeroToleranceViolation:
        # Halt the entire batch — zero-tolerance violations demand HITL.
        raise
    except Exception as e:
        logger.error(f"Error processing draft issue {draft_path}: {e}", exc_info=True)
        return {
            "current_issue_index": idx + 1,
            "succeeded_drafts": [],
            "failed_drafts": [draft_path_str],
        }


def should_continue(state: AgentState) -> str:
    """Determines if there are more draft issues to process."""
    idx = state.get("current_issue_index", 0)
    draft_issues = state.get("draft_issues", [])
    if idx < len(draft_issues):
        return "run_refinement"
    return END


workflow = StateGraph(AgentState)
workflow.add_node("run_refinement", run_refinement_subgraph_node)
workflow.set_entry_point("run_refinement")
workflow.add_conditional_edges(
    "run_refinement",
    should_continue,
    {
        "run_refinement": "run_refinement",
        END: END,
    },
)

graph = workflow.compile()
