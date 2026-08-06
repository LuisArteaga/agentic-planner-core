import logging
from pathlib import Path
from langgraph.graph import StateGraph, END
from planner.state import AgentState, RefinementState
from planner.nodes.analyze_sources import analyze_sources_node
from planner.nodes.web_search import web_search_node
from planner.nodes.propose_options import propose_options_node
from planner.nodes.evaluate_grade import evaluate_grade_node
from planner.nodes.apply_decision import apply_decision_node
from planner.nodes.publish_issue import publish_issue_node

logger = logging.getLogger("planner.refine_graph")

# Define and compile the Refinement Subgraph
subgraph_workflow = StateGraph(RefinementState)
subgraph_workflow.add_node("analyze_sources", analyze_sources_node)
subgraph_workflow.add_node("web_search", web_search_node)
subgraph_workflow.add_node("propose_options", propose_options_node)
subgraph_workflow.add_node("evaluate_grade", evaluate_grade_node)
subgraph_workflow.add_node("apply_decision", apply_decision_node)
subgraph_workflow.add_node("publish_issue", publish_issue_node)

subgraph_workflow.set_entry_point("analyze_sources")
subgraph_workflow.add_edge("analyze_sources", "web_search")
subgraph_workflow.add_edge("web_search", "propose_options")
subgraph_workflow.add_edge("propose_options", "evaluate_grade")
subgraph_workflow.add_edge("evaluate_grade", "apply_decision")
subgraph_workflow.add_edge("apply_decision", "publish_issue")
subgraph_workflow.add_edge("publish_issue", END)

refine_subgraph = subgraph_workflow.compile()


# Define the Master Graph
def run_refinement_subgraph_node(state: AgentState) -> dict:
    """Master node that runs the Refinement Subgraph for the current draft issue."""
    idx = state.get("current_issue_index", 0)
    draft_issues = state.get("draft_issues", [])

    if idx >= len(draft_issues):
        return {"status": "success"}

    draft_path = Path(draft_issues[idx])
    if not draft_path.exists():
        raise FileNotFoundError(f"Draft issue file not found: {draft_path}")

    with open(draft_path, "r", encoding="utf-8") as f:
        draft_content = f.read()

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
    }

    # Execute the subgraph
    try:
        subgraph_output = refine_subgraph.invoke(subgraph_input)
        status = subgraph_output.get("status", "success")
    except Exception as e:
        logger.error(f"Error processing draft issue {draft_path}: {e}", exc_info=True)
        status = "failed"

    return {
        "current_issue_index": idx + 1,
        "status": status,
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
