from typing import Any

from llama_index.core.llms import LLM, ChatMessage
from llama_index.core.workflow import Context, Event, StartEvent, StopEvent, Workflow, step

from omneum import ContextEvaluation, ContextMapper, Observation, open_stdio_client
from examples.context_preparation import PreparationOptions, collect_chunks, prepare_generation
from examples.enterprise.config import example_deployment
from examples.enterprise.workflow.run import QUESTION, collect_observations, estimator_config


class RetrievalResultsEvent(Event):
    results: tuple[Observation, ...]
    question: str = QUESTION
    chunks: list[dict[str, Any]]


class ContextEvaluationEvent(Event):
    result: ContextEvaluation
    observations: tuple[Observation, ...]
    question: str
    chunks: list[dict[str, Any]]


class PreparedContextEvent(Event):
    generation: dict[str, Any]


class EnterpriseWorkflow(Workflow):
    def __init__(self, *, chat_model: LLM | None = None, preparation: PreparationOptions | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.chat_model = chat_model
        self.preparation = preparation or PreparationOptions()

    @step
    async def retrieve(
        self,
        event: StartEvent,
    ) -> RetrievalResultsEvent:
        observations = collect_observations()
        return RetrievalResultsEvent(
            results=observations, chunks=collect_chunks(observations),
            question=event.get("question", QUESTION),
        )

    @step
    async def evaluate(
        self,
        event: RetrievalResultsEvent,
    ) -> ContextEvaluationEvent:
        with example_deployment() as (config, server):
            async with open_stdio_client(config, server) as client:
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
                    event.results,
                    mapper,
                    estimator=estimator_config(),
                )

        return ContextEvaluationEvent(
            result=result, observations=event.results, question=event.question, chunks=event.chunks,
        )

    @step
    async def prepare_context(self, ctx: Context, event: ContextEvaluationEvent) -> PreparedContextEvent:
        generation = await prepare_generation(
            event.observations, question=event.question, estimator=estimator_config(),
            chunks=event.chunks, evaluation=event.result, preparation=self.preparation,
        )
        await ctx.store.set("evaluation", event.result)
        await ctx.store.set("generation", generation)
        return PreparedContextEvent(generation=generation)

    @step
    async def render(
        self,
        ctx: Context,
        event: PreparedContextEvent,
    ) -> StopEvent:
        messages = [ChatMessage(**message) for message in event.generation["messages"]]
        await ctx.store.set("messages", messages)
        if self.chat_model is not None:
            response = await self.chat_model.achat(messages)
            return StopEvent(result=response.message.content)
        return StopEvent(result="Selected context:\n" + messages[1].content)
