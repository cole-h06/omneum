from functools import partial

from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, START, StateGraph

from .nodes import (
    evaluate_context,
    merge_observations,
    prepare_context,
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


def build_graph(*, model: BaseChatModel | None = None):
    graph = StateGraph(WorkflowState)

    graph.add_node("retrieve_documents", retrieve_documents)
    graph.add_node("retrieve_research", retrieve_research)
    graph.add_node("retrieve_sql", retrieve_sql)
    graph.add_node("retrieve_api", retrieve_api)
    graph.add_node("retrieve_search", retrieve_search)
    graph.add_node("merge_observations", merge_observations)
    graph.add_node("evaluate_context", evaluate_context)
    graph.add_node("render_answer", partial(render_answer, model=model))
    graph.add_node("prepare_context", prepare_context)

    for node in _RETRIEVAL_NODES:
        graph.add_edge(START, node)
        graph.add_edge(node, "merge_observations")

    graph.add_edge("merge_observations", "evaluate_context")
    graph.add_edge("evaluate_context", "prepare_context")
    graph.add_edge("prepare_context", "render_answer")
    graph.add_edge("render_answer", END)

    return graph.compile()
