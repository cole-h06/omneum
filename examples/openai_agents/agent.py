from agents import Agent, Runner, function_tool

from examples.context_preparation import GenerationInput, PreparationOptions, prepare_generation
from examples.enterprise.workflow.run import QUESTION, collect_observations, estimator_config


@function_tool(failure_error_function=None)
async def evaluate_context(question: str = QUESTION) -> str:
    """Prepare original enterprise evidence and source references for the question."""
    generation = await prepare_generation(
        collect_observations(), question=question, estimator=estimator_config(),
    )
    return generation["messages"][1]["content"]


agent = Agent(
    name="Enterprise AI Assistant",
    instructions=(
        "Answer deployment-readiness questions using the "
        "evaluate_context tool with the user's question before answering. "
        "Use its retrieved passages as evidence, cite chunk IDs, and explain conflicts."
    ),
    tools=[evaluate_context],
)


async def run_agent(
    question: str = QUESTION, *, preparation: PreparationOptions | None = None,
    generation_agent: Agent | None = None, inspect_context: bool = False,
) -> tuple[GenerationInput, str | None]:
    generation = await prepare_generation(
        collect_observations(), question=question, estimator=estimator_config(), preparation=preparation,
    )
    if inspect_context:
        return generation, None
    consumer = generation_agent or agent.clone(instructions=generation["messages"][0]["content"], tools=[])
    result = await Runner.run(consumer, generation["messages"])
    return generation, result.final_output
