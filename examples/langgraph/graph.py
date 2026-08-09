from langgraph.graph import END, START, StateGraph

from .nodes import (
    evaluate_assertion,
    merge_observations,
    render_answer,
    retrieve_api,
    retrieve_documents,
    retrieve_research,
    retrieve_search,
    retrieve_sql,
)
from .state import WorkflowState


_RETRIEVAL_NODES = (
    "retrieve_documents",
    "retrieve_research",
    "retrieve_sql",
    "retrieve_api",
    "retrieve_search",
)


def build_graph():
    graph = StateGraph(WorkflowState)

    graph.add_node("retrieve_documents", retrieve_documents)
    graph.add_node("retrieve_research", retrieve_research)
    graph.add_node("retrieve_sql", retrieve_sql)
    graph.add_node("retrieve_api", retrieve_api)
    graph.add_node("retrieve_search", retrieve_search)
    graph.add_node("merge_observations", merge_observations)
    graph.add_node("evaluate_assertion", evaluate_assertion)
    graph.add_node("render_answer", render_answer)

    for node in _RETRIEVAL_NODES:
        graph.add_edge(START, node)
        graph.add_edge(node, "merge_observations")

    graph.add_edge("merge_observations", "evaluate_assertion")
    graph.add_edge("evaluate_assertion", "render_answer")
    graph.add_edge("render_answer", END)

    return graph.compile()