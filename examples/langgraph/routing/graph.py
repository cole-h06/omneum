from functools import partial

from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, START, StateGraph

from examples.langgraph.nodes import (
    evaluate_context,
    merge_observations,
    prepare_context,
    retrieve_api,
    retrieve_documents,
    retrieve_research,
    retrieve_search,
    retrieve_sql,
)
from examples.langgraph.state import WorkflowState

from .policy import assess_context
from examples.langgraph.nodes import render_answer

from .selection import select_context
from .retrieval import retrieve_additional_evidence


def route_context(state: WorkflowState) -> str:
    decision = assess_context(
        state["context_evaluation"],
        retries=state.get("retry_count", 0),
    )
    return decision.route


def _retry(state: WorkflowState, route: str) -> dict:
    decision = assess_context(
        state["context_evaluation"],
        retries=state.get("retry_count", 0),
    )

    existing = state["observations"]
    known_ids = {item.observation_id for item in existing}

    additional = retrieve_additional_evidence(
        decision.attributes,
        strategy=route,
        attempt=state.get("retry_count", 0) + 1,
    )

    new_observations = tuple(
        item
        for item in additional
        if item.observation_id not in known_ids
    )

    return {
        "observations": (*existing, *new_observations),
        "retry_count": state.get("retry_count", 0) + 1,
        "routing_history": (
            *state.get("routing_history", ()),
            route,
        ),
    }


def retrieve_support(state: WorkflowState) -> dict:
    return _retry(state, "retrieve_support")


def resolve_conflicts(state: WorkflowState) -> dict:
    return _retry(state, "resolve_conflicts")


def diversify_sources(state: WorkflowState) -> dict:
    return _retry(state, "diversify_sources")


def select_claims(state: WorkflowState) -> dict:
    return {
        "selected_claims": select_context(state["context_evaluation"]),
    }


async def generate(state: WorkflowState, *, model: BaseChatModel | None = None) -> dict:
    result = await render_answer(state, model=model)
    if model is None:
        result["answer"] = "Application decision: EVALUATION COMPLETE\n" + result["answer"]
    return result

def escalate(state: WorkflowState) -> dict:
    return {
        "answer": (
            "Application decision: ESCALATE\n"
            "Evidence did not meet the routing policy."
        )
    }


def build_routing_graph(*, preloaded=False, model: BaseChatModel | None = None):
    graph = StateGraph(WorkflowState)

    retrieval_nodes = {
        "retrieve_documents": retrieve_documents,
        "retrieve_research": retrieve_research,
        "retrieve_sql": retrieve_sql,
        "retrieve_api": retrieve_api,
        "retrieve_search": retrieve_search,
    }

    if preloaded:
        graph.add_edge(START, "evaluate_context")
    else:
        for name, node in retrieval_nodes.items():
            graph.add_node(name, node)
            graph.add_edge(START, name)
            graph.add_edge(name, "merge_observations")

    if not preloaded:
        graph.add_node("merge_observations", merge_observations)
    graph.add_node("evaluate_context", evaluate_context)
    graph.add_node("retrieve_support", retrieve_support)
    graph.add_node("resolve_conflicts", resolve_conflicts)
    graph.add_node("diversify_sources", diversify_sources)
    graph.add_node("select_context", select_claims)
    graph.add_node("generate", partial(generate, model=model))
    graph.add_node("prepare_context", prepare_context)
    graph.add_node("escalate", escalate)

    if not preloaded:
        graph.add_edge("merge_observations", "evaluate_context")

    graph.add_conditional_edges(
        "evaluate_context",
        route_context,
        {
            "generate": "select_context",
            "retrieve_support": "retrieve_support",
            "resolve_conflicts": "resolve_conflicts",
            "diversify_sources": "diversify_sources",
            "escalate": "escalate",
        },
    )

    for name in (
        "retrieve_support",
        "resolve_conflicts",
        "diversify_sources",
    ):
        graph.add_edge(name, "evaluate_context")

    graph.add_edge("select_context", "prepare_context")
    graph.add_edge("prepare_context", "generate")
    graph.add_edge("generate", END)
    graph.add_edge("escalate", END)

    return graph.compile()
