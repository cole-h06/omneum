import os

from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool

from examples.enterprise.config import example_deployment
from examples.enterprise.workflow.run import collect_observations, estimator_config, render_result

from omneum import ContextMapper, open_stdio_client


async def evaluate_context() -> str:
    """Retrieve enterprise evidence and return the Omneum evaluation report."""

    with example_deployment() as (config, server):
        async with open_stdio_client(config, server) as client:
            observations = collect_observations()

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
                    name: lambda x, name=name: x.dependency_signals.get(name)
                    for name in (
                        "upstream", "citation", "assertion_lineage", "ownership",
                        "temporal", "graph", "retrieval",
                    )
                },
            )

            result = await client.evaluate_mapped(
                observations,
                mapper,
                estimator=estimator_config(),
            )

    return render_result(result)


evaluation_tool = FunctionTool(evaluate_context)


def build_agent() -> LlmAgent:
    return LlmAgent(
        name="enterprise_assistant",
        model=os.environ.get("GOOGLE_ADK_MODEL", "gemini-3.8-flash"),
        instruction=(
            "Answer deployment-readiness questions using the evaluate_context tool. "
            "Call the tool before answering. Base your response on its evaluation "
            "report, including conflicting claims and source dependencies."
        ),
        tools=[evaluation_tool],
    )


agent = build_agent()
