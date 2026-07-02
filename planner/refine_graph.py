from pathlib import Path
from langgraph.graph import StateGraph, END
from planner.state import AgentState, RefinementState
from planner.nodes.analyze_sources import analyze_sources_node
from planner.nodes.web_search import web_search_node

# Define and compile the Refinement Subgraph
subgraph_workflow = StateGraph(RefinementState)
subgraph_workflow.add_node("analyze_sources", analyze_sources_node)
subgraph_workflow.add_node("web_search", web_search_node)

subgraph_workflow.set_entry_point("analyze_sources")
subgraph_workflow.add_edge("analyze_sources", "web_search")
subgraph_workflow.add_edge("web_search", END)

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

    subgraph_input = {
        "draft_issue_content": draft_content,
        "strict_mode": state.get("strict_mode", True),
        "allowed_domains": state.get("allowed_domains", []),
        "messages": [],
        "keywords": [],
        "search_queries": [],
        "search_results": [],
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "model_name": "",
        "status": "idle",
    }

    # Execute the subgraph
    subgraph_output = refine_subgraph.invoke(subgraph_input)

    return {
        "current_issue_index": idx + 1,
        "status": subgraph_output.get("status", "success"),
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
