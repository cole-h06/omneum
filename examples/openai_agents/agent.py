from agents import Agent, function_tool

from examples.enterprise.config import example_deployment
from examples.enterprise.workflow.run import collect_observations, estimator_config, render_result
from omneum import ContextMapper, open_stdio_client


@function_tool
async def evaluate_assertion() -> str:
    """Evaluate the retrieved observations with Omneum.

    Returns a formatted summary of the assertion evaluation results.
    """

    with example_deployment() as (config, server):
        async with open_stdio_client(config, server) as client:
            observations = collect_observations()

            mapper = ContextMapper(
                source=lambda x: x.source,
                entity_namespace=lambda x: x.claim.entity_namespace,
                entity=lambda x: x.claim.entity,
                attribute=lambda x: x.claim.attribute,
                value=lambda x: x.claim.value,
                assertion_id=lambda x: x.assertion_id,
                observed_at=lambda x: x.observed_at,
                source_modified_at=lambda x: x.source_modified_at,
                upstream_sources=lambda x: x.upstream_sources,
                cited_sources=lambda x: x.cited_sources,
                parent_assertion_ids=lambda x: x.parent_assertion_ids,
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
                observations,
                mapper,
                estimator=estimator_config(),
            )

    return render_result(result)


agent = Agent(
    name="Enterprise AI Assistant",
    instructions=(
        "Answer deployment-readiness questions using the "
        "evaluate_assertion tool. Base your response on the "
        "assertion evaluation results."
    ),
    tools=[evaluate_assertion],
)