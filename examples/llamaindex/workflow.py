from llama_index.core.workflow import Workflow, step, StartEvent, StopEvent, Event

from examples.enterprise.config import example_deployment
from examples.enterprise.workflow.run import collect_observations, estimator_config, render_result

from verity import AssertionEvaluation, Observation, open_stdio_client


class ObservationsEvent(Event):
    observations: tuple[Observation, ...]


class AssertionEvaluationEvent(Event):
    result: AssertionEvaluation


class EnterpriseWorkflow(Workflow):
    @step
    async def retrieve(
        self,
        _: StartEvent,
    ) -> ObservationsEvent:
        return ObservationsEvent(
            observations=collect_observations(),
        )

    @step
    async def evaluate(
        self,
        event: ObservationsEvent,
    ) -> AssertionEvaluationEvent:
        with example_deployment() as (config, server):
            async with open_stdio_client(config, server) as client:
                result = await client.evaluate_assertion(
                    event.observations,
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