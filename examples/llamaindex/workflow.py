from llama_index.core.workflow import Workflow, step, StartEvent, StopEvent, Event

from examples.enterprise.config import example_deployment
from examples.enterprise.workflow.run import collect_observations, estimator_config, render_result

from omneum import AssertionEvaluation, ContextMapper, Observation, open_stdio_client


class RetrievalResultsEvent(Event):
    results: tuple[Observation, ...]


class AssertionEvaluationEvent(Event):
    result: AssertionEvaluation


class EnterpriseWorkflow(Workflow):
    @step
    async def retrieve(
        self,
        _: StartEvent,
    ) -> RetrievalResultsEvent:
        return RetrievalResultsEvent(
            results=collect_observations(),
        )

    @step
    async def evaluate(
        self,
        event: RetrievalResultsEvent,
    ) -> AssertionEvaluationEvent:
        with example_deployment() as (config, server):
            async with open_stdio_client(config, server) as client:
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
                    event.results,
                    mapper,
                    estimator=estimator_config(),
                )

        return AssertionEvaluationEvent(result=result)

    @step
    async def render(
        self,
        event: AssertionEvaluationEvent,
    ) -> StopEvent:
        return StopEvent(
            result=render_result(event.result),
        )