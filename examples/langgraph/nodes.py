from examples.enterprise.agents.api import api_agent
from examples.enterprise.agents.documents import documents_agent
from examples.enterprise.agents.research import research_agent
from examples.enterprise.agents.search import search_agent
from examples.enterprise.agents.sql import sql_agent
from examples.enterprise.config import example_deployment
from examples.enterprise.workflow.run import estimator_config, render_result
from verity import Observation, open_stdio_client

from .state import ObservationBatch, WorkflowState


# Parallel branches may finish in any order. 
# Restore canonical retrieval order before evaluation so results stay stable.
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


async def evaluate_assertion(state: WorkflowState) -> dict[str, object]:
    # Reuse the deterministic deployment owned by the canonical example.
    with example_deployment() as (config, server):
        async with open_stdio_client(config, server) as client:
            result = await client.evaluate_assertion(
                state["observations"],
                estimator=estimator_config(),
            )

    return {"assertion_evaluation": result}


def render_answer(state: WorkflowState) -> dict[str, str]:
    return {
        "answer": render_result(state["assertion_evaluation"]),
    }
