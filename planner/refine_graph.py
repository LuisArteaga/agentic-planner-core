from typing import TypedDict
from langgraph.graph import StateGraph, END


class AgentState(TypedDict):
    status: str


def dummy_node(state: AgentState) -> AgentState:
    return {"status": "initialized"}


workflow = StateGraph(AgentState)
workflow.add_node("init", dummy_node)
workflow.set_entry_point("init")
workflow.add_edge("init", END)

graph = workflow.compile()
