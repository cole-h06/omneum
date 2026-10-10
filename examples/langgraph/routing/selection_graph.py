from langgraph.graph import END, START, StateGraph

from examples.langgraph.nodes import evaluate_context
from examples.langgraph.state import WorkflowState

from .selection import select_context


def select_claims(state: WorkflowState) -> dict:
    return {
        "selected_claims": select_context(state["context_evaluation"]),
    }


def generate_selected(state: WorkflowState) -> dict:
    claims = state["selected_claims"]

    lines = [
        "Selected context:",
        *(
            f"{claim.attribute}: {claim.value}"
            for claim in claims
        ),
    ]

    return {"answer": "\n".join(lines)}


def build_selection_graph():
    graph = StateGraph(WorkflowState)

    graph.add_node("evaluate_context", evaluate_context)
    graph.add_node("select_context", select_claims)
    graph.add_node("generate", generate_selected)

    graph.add_edge(START, "evaluate_context")
    graph.add_edge("evaluate_context", "select_context")
    graph.add_edge("select_context", "generate")
    graph.add_edge("generate", END)

    return graph.compile()
