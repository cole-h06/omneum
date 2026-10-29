from agent_framework import Agent, Message

from examples.context_preparation import GenerationInput, PreparationOptions, prepare_generation
from examples.enterprise.workflow.run import QUESTION, collect_observations, estimator_config


async def evaluate_context(question: str = QUESTION) -> str:
    """Prepare original enterprise evidence and source references for the question."""
    generation = await prepare_generation(
        collect_observations(), question=question, estimator=estimator_config(),
    )
    return generation["messages"][1]["content"]


async def run_agent(
    question: str = QUESTION, *, preparation: PreparationOptions | None = None,
    generation_agent: Agent | None = None, inspect_context: bool = False,
) -> tuple[GenerationInput, str | None]:
    generation = await prepare_generation(
        collect_observations(), question=question, estimator=estimator_config(), preparation=preparation,
    )
    if inspect_context:
        return generation, None
    if generation_agent is None:
        from .agent import agent

        generation_agent = Agent(
            client=agent.client, name="enterprise_generation",
            instructions=generation["messages"][0]["content"],
        )
    messages = [Message(message["role"], contents=[message["content"]]) for message in generation["messages"]]
    response = await generation_agent.run(messages)
    return generation, response.text
