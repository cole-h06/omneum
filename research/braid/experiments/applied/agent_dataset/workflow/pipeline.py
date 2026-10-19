from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from omneum import ContextEvaluation, evaluate_context

from .....adapters.observations import estimator, to_observations
from ..agents.api import api_agent
from ..agents.documents import document_agent
from ..agents.research import research_agent
from ..agents.search import search_agent
from ..agents.sql import sql_agent
from ..dataset import DEPENDENCY_WEIGHTS, SOURCES, validate_dataset
from ..extraction.schema import (
    AgentResult,
    Observation,
    SourceMetadata,
)


AGENT_ORDER = (
    "research_agent",
    "search_agent",
    "sql_agent",
    "document_agent",
    "api_agent",
)


def merge_results(
    left,
    right,
):

    overlap = left.keys() & right.keys()

    if overlap:
        raise ValueError("agent result already exists")

    return {
        **left,
        **right,
    }


class WorkflowState(TypedDict, total=False):

    results: Annotated[
        dict[str, AgentResult],
        merge_results,
    ]

    sources: tuple[SourceMetadata, ...]

    observations: list[Observation]

    evaluation: ContextEvaluation


def research_node(state):

    return {
        "results": {
            "research_agent": research_agent(),
        }
    }


def search_node(state):

    return {
        "results": {
            "search_agent": search_agent(),
        }
    }


def sql_node(state):

    return {
        "results": {
            "sql_agent": sql_agent(),
        }
    }


def document_node(state):

    return {
        "results": {
            "document_agent": document_agent(),
        }
    }


def api_node(state):

    return {
        "results": {
            "api_agent": api_agent(),
        }
    }


def validate_node(state):

    validate_dataset(
        state["sources"],
        state["observations"],
    )

    return {}


def build_pipeline(
    agent_nodes,
    order,
    sources,
    roots,
    collect_from,
    joins=(),
    weights=None,
):

    weights = (
        DEPENDENCY_WEIGHTS
        if weights is None
        else weights
    )

    def evaluation_node(state):

        return {
            "evaluation": evaluate_context(
                to_observations(state["sources"], state["observations"]),
                estimator=estimator(weights),
            ),
        }

    def collect_node(state):

        observations = []

        # keep collection stable after the parallel agent nodes finish
        for source_id in order:

            result = state["results"][source_id]

            observations.extend(result.observations)

        return {
            "sources": sources,
            "observations": observations,
        }

    workflow = StateGraph(WorkflowState)

    for name, node in agent_nodes.items():
        workflow.add_node(name, node)

    workflow.add_node("collect", collect_node)
    workflow.add_node("validate", validate_node)
    workflow.add_node("evaluation", evaluation_node)

    for agent in roots:
        workflow.add_edge(START, agent)

    for parents, child in joins:
        workflow.add_edge(parents, child)

    # wait for every terminal agent before collecting their results
    workflow.add_edge(collect_from, "collect")

    workflow.add_edge("collect", "validate")
    workflow.add_edge("validate", "evaluation")
    workflow.add_edge("evaluation", END)

    return workflow.compile()


def build_workflow(
    weights=None,
):

    agents = {
        "research": research_node,
        "search": search_node,
        "sql": sql_node,
        "document": document_node,
        "api": api_node,
    }

    return build_pipeline(
        agent_nodes=agents,
        order=AGENT_ORDER,
        sources=SOURCES,
        roots=tuple(agents),
        collect_from=tuple(agents),
        weights=weights,
    )


def run_workflow(
    weights=None,
):

    workflow = build_workflow(
        weights=weights,
    )

    state = workflow.invoke({
        "results": {},
    })

    return {
        "sources": state["sources"],
        "observations": state["observations"],
        "evaluation": state["evaluation"],
    }
