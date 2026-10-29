import os

from google.adk.agents import LlmAgent
from google.adk.models import BaseLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from google.adk.tools import FunctionTool

from examples.context_preparation import GenerationInput, PreparationOptions, prepare_generation
from examples.enterprise.workflow.run import QUESTION, collect_observations, estimator_config


async def evaluate_context(question: str = QUESTION) -> str:
    """Prepare original enterprise evidence and source references for the question."""
    generation = await prepare_generation(
        collect_observations(), question=question, estimator=estimator_config(),
    )
    return generation["messages"][1]["content"]


evaluation_tool = FunctionTool(evaluate_context)


def build_agent(*, prepared: bool = False, model: BaseLlm | str | None = None) -> LlmAgent:
    return LlmAgent(
        name="enterprise_assistant",
        model=model if model is not None else os.environ.get("GOOGLE_ADK_MODEL", "gemini-3.8-flash"),
        instruction="Answer using only the supplied original passages; cite chunk IDs and explain conflicts." if prepared else (
            "Answer deployment-readiness questions using the evaluate_context tool. "
            "Pass the user's question to the tool before answering. Use its original "
            "passages as evidence, cite chunk IDs, and explain conflicts."
        ),
        tools=[] if prepared else [evaluation_tool],
    )


agent = build_agent()


async def run_agent(
    question: str = QUESTION, *, preparation: PreparationOptions | None = None,
    generation_agent: LlmAgent | None = None, inspect_context: bool = False,
) -> tuple[GenerationInput, str | None]:
    generation = await prepare_generation(
        collect_observations(), question=question, estimator=estimator_config(), preparation=preparation,
    )
    if inspect_context:
        return generation, None
    consumer = generation_agent or build_agent(prepared=True)
    sessions = InMemorySessionService()
    session = await sessions.create_session(app_name="omneum_generation", user_id="example")
    runner = Runner(agent=consumer, app_name=session.app_name, session_service=sessions)
    answer = None
    try:
        async for event in runner.run_async(
            user_id=session.user_id, session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text=generation["messages"][1]["content"])]),
        ):
            if event.is_final_response() and event.content is not None:
                answer = "".join(part.text for part in event.content.parts if part.text is not None)
    finally:
        await runner.close()
    if answer is None:
        raise RuntimeError("The agent returned no final text response")
    return generation, answer
