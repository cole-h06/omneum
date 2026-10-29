"""Omneum conditional routing through LlamaIndex's native typed events."""

from typing import Any

from llama_index.core.llms import LLM, ChatMessage
from llama_index.core.workflow import Context, Event, StartEvent, StopEvent, Workflow, step

from examples.context_preparation import PreparationOptions, collect_chunks, prepare_generation

from examples.enterprise.config import example_deployment
from examples.enterprise.workflow.run import estimator_config
from examples.langgraph.routing.policy import assess_context
from examples.langgraph.routing.retrieval import retrieve_additional_evidence
from examples.langgraph.routing.scenarios import initial_observations
from examples.langgraph.routing.selection import select_context
from omneum import open_stdio_client

from .state import RoutingState


class EvidenceEvent(Event):
    state: RoutingState


class EvaluatedEvent(Event):
    state: RoutingState


class RetrieveSupportEvent(Event):
    state: RoutingState


class ResolveConflictsEvent(Event):
    state: RoutingState


class DiversifySourcesEvent(Event):
    state: RoutingState


class SelectContextEvent(Event):
    state: RoutingState


class GenerateEvent(Event):
    state: RoutingState


class EscalateEvent(Event):
    state: RoutingState


def emit(ctx: Context, event: Event):
    """Expose a snapshot for diagnostics without dispatching a second event."""
    ctx.write_event_to_stream(event.model_copy(deep=True))
    return event


class RoutingWorkflow(Workflow):
    def __init__(self, *, chat_model: LLM | None = None, preparation: PreparationOptions | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.chat_model = chat_model
        self.preparation = preparation or PreparationOptions()

    @step
    async def load_evidence(self, ctx: Context, event: StartEvent) -> EvidenceEvent:
        scenario = event.get("scenario", "diversify_sources")
        observations = initial_observations(scenario)
        state = RoutingState(
            scenario=scenario, preparation=self.preparation,
            initial_observation_count=len(observations),
            observations=observations,
        )
        return emit(ctx, EvidenceEvent(state=state))

    @step
    async def evaluate_context(self, ctx: Context, event: EvidenceEvent) -> EvaluatedEvent:
        state = event.state
        state.retrieved_chunks = collect_chunks(state.observations)
        with example_deployment() as (config, server):
            async with open_stdio_client(config, server) as client:
                state.context_evaluation = await client.evaluate_context(
                    state.observations,
                    estimator=estimator_config(),
                )
        return emit(ctx, EvaluatedEvent(state=state))

    @step
    async def route_context(
        self, ctx: Context, event: EvaluatedEvent,
    ) -> RetrieveSupportEvent | ResolveConflictsEvent | DiversifySourcesEvent | SelectContextEvent | EscalateEvent:
        state = event.state
        decision = assess_context(
            state.context_evaluation,
            retries=state.retry_count,
        )
        state.decision = decision
        state.routing_history = (*state.routing_history, decision.route)
        event_type = {
            "retrieve_support": RetrieveSupportEvent,
            "resolve_conflicts": ResolveConflictsEvent,
            "diversify_sources": DiversifySourcesEvent,
            "generate": SelectContextEvent,
            "escalate": EscalateEvent,
        }[decision.route]
        return emit(ctx, event_type(state=state))

    def _retrieve(self, state: RoutingState, strategy: str) -> EvidenceEvent:
        known_ids = {item.observation_id for item in state.observations}
        additional = retrieve_additional_evidence(
            state.decision.attributes,
            strategy=strategy,
            attempt=state.retry_count + 1,
        )
        new_observations = []
        for item in additional:
            if item.observation_id not in known_ids:
                new_observations.append(item)
                known_ids.add(item.observation_id)
        state.observations = (*state.observations, *new_observations)
        state.retry_count += 1
        return EvidenceEvent(state=state)

    @step
    async def retrieve_support(self, ctx: Context, event: RetrieveSupportEvent) -> EvidenceEvent:
        return emit(ctx, self._retrieve(event.state, "retrieve_support"))

    @step
    async def resolve_conflicts(self, ctx: Context, event: ResolveConflictsEvent) -> EvidenceEvent:
        return emit(ctx, self._retrieve(event.state, "resolve_conflicts"))

    @step
    async def diversify_sources(self, ctx: Context, event: DiversifySourcesEvent) -> EvidenceEvent:
        return emit(ctx, self._retrieve(event.state, "diversify_sources"))

    @step
    async def select_claims(self, ctx: Context, event: SelectContextEvent) -> GenerateEvent:
        state = event.state
        state.selected_claims = select_context(state.context_evaluation)
        state.generation = await prepare_generation(
            state.observations, question=state.question, estimator=estimator_config(),
            chunks=state.retrieved_chunks, evaluation=state.context_evaluation,
            preparation=state.preparation,
        )
        state.messages = [ChatMessage(**message) for message in state.generation["messages"]]
        return emit(ctx, GenerateEvent(state=state))

    @step
    async def generate_answer(self, event: GenerateEvent) -> StopEvent:
        state = event.state
        state.answer = (
            "Application decision: EVALUATION COMPLETE\nSelected context:\n"
            + state.messages[1].content
        )
        if self.chat_model is not None:
            response = await self.chat_model.achat(state.messages)
            state.answer = response.message.content
        return StopEvent(result=state)

    @step
    async def escalate_answer(self, event: EscalateEvent) -> StopEvent:
        state = event.state
        state.answer = (
            "Application decision: ESCALATE\n"
            "Evidence did not meet the routing policy."
        )
        return StopEvent(result=state)
