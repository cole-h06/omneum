from collections.abc import AsyncGenerator

from google.adk.agents import BaseAgent, LlmAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from examples.context_preparation import PreparationOptions, collect_chunks, prepare_generation
from examples.enterprise.config import example_deployment
from examples.enterprise.workflow.run import QUESTION, estimator_config
from examples.langgraph.routing.policy import RoutingPolicy, assess_context
from examples.langgraph.routing.retrieval import retrieve_additional_evidence
from examples.langgraph.routing.scenarios import initial_observations
from examples.langgraph.routing.selection import select_context
from omneum import open_stdio_client

from .state import RoutingState


class RoutingAgent(BaseAgent):
    state: RoutingState
    policy: RoutingPolicy = RoutingPolicy()
    generation_agent: LlmAgent | None = None

    def stage_event(self, ctx: InvocationContext, stage: str) -> Event:
        state = self.state
        state.stage_history = (*state.stage_history, stage)
        return Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            actions=EventActions(state_delta={
                "stage": stage,
                "observation_count": len(state.observations),
                "retry_count": state.retry_count,
                "routing_history": list(state.routing_history),
            }),
        )

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        state = self.state
        state.observations = initial_observations(state.scenario)
        state.initial_observation_count = len(state.observations)
        yield self.stage_event(ctx, "load_evidence")
        while True:
            state.retrieved_chunks = collect_chunks(state.observations)
            with example_deployment() as (config, server):
                async with open_stdio_client(config, server) as client:
                    state.context_evaluation = await client.evaluate_context(
                        state.observations, estimator=estimator_config(),
                    )
            yield self.stage_event(ctx, "evaluate_context")
            state.decision = assess_context(
                state.context_evaluation, retries=state.retry_count, policy=self.policy,
            )
            route = state.decision.route
            state.routing_history = (*state.routing_history, route)
            yield self.stage_event(ctx, "route_context")
            if route == "generate":
                state.selected_claims = select_context(state.context_evaluation, policy=self.policy)
                state.generation = await prepare_generation(
                    state.observations, question=state.question, estimator=estimator_config(),
                    chunks=state.retrieved_chunks, evaluation=state.context_evaluation,
                    preparation=state.preparation,
                )
                state.generation_content = types.Content(
                    role="user", parts=[types.Part(text=state.generation["messages"][1]["content"])],
                )
                yield self.stage_event(ctx, "select_context")
                state.answer = (
                    "Application decision: EVALUATION COMPLETE\nSelected context:\n"
                    + state.generation_content.parts[0].text
                )
                if self.generation_agent is not None:
                    yield Event(
                        invocation_id=ctx.invocation_id, author="user", content=state.generation_content,
                    )
                    answer = None
                    async for event in self.generation_agent.run_async(ctx):
                        if event.is_final_response() and event.content is not None:
                            texts = [part.text for part in event.content.parts or [] if part.text is not None]
                            if texts:
                                answer = "".join(texts)
                        yield event
                    if answer is None:
                        raise RuntimeError("The generation agent returned no final text response")
                    state.answer = answer
                break
            if route == "escalate":
                state.answer = (
                    "Application decision: ESCALATE\n"
                    "Evidence did not meet the routing policy."
                )
                break
            additional = retrieve_additional_evidence(
                state.decision.attributes, strategy=route, attempt=state.retry_count + 1,
            )
            known_ids = {item.observation_id for item in state.observations}
            new_observations = []
            for item in additional:
                if item.observation_id not in known_ids:
                    new_observations.append(item)
                    known_ids.add(item.observation_id)
            state.observations = (*state.observations, *new_observations)
            state.retry_count += 1
            yield self.stage_event(ctx, route)
        yield self.stage_event(ctx, route)
        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            actions=EventActions(state_delta={
                "answer": state.answer,
                "generation_input": state.generation_content.model_dump(mode="json")
                if state.generation_content is not None else None,
            }),
        )


async def run_routing(
    scenario: str, *, policy: RoutingPolicy = RoutingPolicy(),
    preparation: PreparationOptions | None = None, generation_agent: LlmAgent | None = None,
) -> RoutingState:
    state = RoutingState(scenario, 0, ())
    state.preparation = preparation or PreparationOptions()
    agent = RoutingAgent(
        name="omneum_routing", state=state, policy=policy, generation_agent=generation_agent,
        sub_agents=[] if generation_agent is None else [generation_agent],
    )
    sessions = InMemorySessionService()
    session = await sessions.create_session(app_name="omneum_routing", user_id="example")
    runner = Runner(agent=agent, app_name=session.app_name, session_service=sessions)
    try:
        async for _ in runner.run_async(
            user_id=session.user_id,
            session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text=QUESTION)]),
        ):
            pass
    finally:
        await runner.close()
    return agent.state
