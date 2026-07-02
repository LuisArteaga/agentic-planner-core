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
    """Master node that runs the Refinement Subgraph for each draft issue."""
    # Proof of concept: run the subgraph on a mock issue
    subgraph_input = {
        "draft_issue_content": "Draft: Implement OpenRouter web search integration for the planner core.",
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

    return {"status": subgraph_output.get("status", "success")}


workflow = StateGraph(AgentState)
workflow.add_node("run_refinement", run_refinement_subgraph_node)
workflow.set_entry_point("run_refinement")
workflow.add_edge("run_refinement", END)

graph = workflow.compile()
