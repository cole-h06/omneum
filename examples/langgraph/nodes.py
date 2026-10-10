from examples.enterprise.agents.api import api_agent
from examples.enterprise.agents.documents import documents_agent
from examples.enterprise.agents.research import research_agent
from examples.enterprise.agents.search import search_agent
from examples.enterprise.agents.sql import sql_agent
from examples.enterprise.config import example_deployment
from examples.enterprise.workflow.run import estimator_config, render_result
from omneum import ContextMapper, Observation, open_stdio_client

from .state import ObservationBatch, WorkflowState


# Preserve retrieval order across parallel branches.
_AGENT_ORDER = {
    "documents": 0,
    "research": 1,
    "sql": 2,
    "api": 3,
    "search": 4,
}


def retrieve_documents(_: WorkflowState) -> dict[str, list[ObservationBatch]]:
    return {
        "observation_batches": [
            {
                "agent": "documents",
                "observations": documents_agent(),
            }
        ]
    }


def retrieve_research(_: WorkflowState) -> dict[str, list[ObservationBatch]]:
    return {
        "observation_batches": [
            {
                "agent": "research",
                "observations": research_agent(),
            }
        ]
    }


def retrieve_sql(_: WorkflowState) -> dict[str, list[ObservationBatch]]:
    return {
        "observation_batches": [
            {
                "agent": "sql",
                "observations": sql_agent(),
            }
        ]
    }


def retrieve_api(_: WorkflowState) -> dict[str, list[ObservationBatch]]:
    return {
        "observation_batches": [
            {
                "agent": "api",
                "observations": api_agent(),
            }
        ]
    }


def retrieve_search(_: WorkflowState) -> dict[str, list[ObservationBatch]]:
    return {
        "observation_batches": [
            {
                "agent": "search",
                "observations": search_agent(),
            }
        ]
    }


def merge_observations(
    state: WorkflowState,
) -> dict[str, tuple[Observation, ...]]:
    batches = sorted(
        state["observation_batches"],
        key=lambda batch: _AGENT_ORDER[batch["agent"]],
    )
    observations = tuple(
        observation
        for batch in batches
        for observation in batch["observations"]
    )
    return {"observations": observations}


async def evaluate_context(state: WorkflowState) -> dict[str, object]:
    # Reuse the deterministic deployment owned by the canonical example.
    with example_deployment() as (config, server):
        async with open_stdio_client(config, server) as client:
            mapper = ContextMapper(
                source=lambda x: x.source,
                entity_namespace=lambda x: x.claim.entity_namespace,
                entity=lambda x: x.claim.entity,
                attribute=lambda x: x.claim.attribute,
                value=lambda x: x.claim.value,
                observation_id=lambda x: x.observation_id,
                observed_at=lambda x: x.observed_at,
                source_modified_at=lambda x: x.source_modified_at,
                upstream_sources=lambda x: x.upstream_sources,
                cited_sources=lambda x: x.cited_sources,
                parent_observation_ids=lambda x: x.parent_observation_ids,
                retrievals=lambda x: x.retrievals,
                signals={
                        name: lambda x, name=name: x.dependency_signals.get(
                            name
                        )
                        for name in (
                            "upstream",
                            "citation",
                            "assertion_lineage",
                            "ownership",
                            "temporal",
                            "graph",
                            "retrieval",
                        )
                    },
            )

            result = await client.evaluate_mapped(
                state["observations"],
                mapper,
                estimator=estimator_config(),
            )

    return {"context_evaluation": result}


def render_answer(state: WorkflowState) -> dict[str, str]:
    return {
        "answer": render_result(state["context_evaluation"]),
    }
