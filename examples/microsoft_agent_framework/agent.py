from agent_framework import Agent
from agent_framework.openai import OpenAIChatClient

from examples.enterprise.config import example_deployment
from examples.enterprise.workflow.run import collect_observations, estimator_config, render_result

from verity import open_stdio_client


async def evaluate_assertion() -> str:
    """Evaluate the enterprise observations with Verity.

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
    client=OpenAIChatClient(),
    name="Enterprise AI Assistant",
    instructions=(
        "Answer deployment-readiness questions using the "
        "evaluate_assertion tool. Base your response on the "
        "assertion evaluation results."
    ),
    tools=[evaluate_assertion],
)