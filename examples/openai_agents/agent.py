from agents import Agent, function_tool

from examples.enterprise.config import example_deployment
from examples.enterprise.workflow.run import collect_observations, estimator_config, render_result
from omneum import open_stdio_client


@function_tool
async def evaluate_assertion() -> str:
    """Evaluate the retrieved observations with Omneum.

    Returns a formatted summary of the assertion evaluation results.
    """

    with example_deployment() as (config, server):
        async with open_stdio_client(config, server) as client:
            result = await client.evaluate_assertion(
                collect_observations(),
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