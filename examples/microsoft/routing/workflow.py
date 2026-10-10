from agent_framework import Executor, Workflow, WorkflowBuilder, WorkflowContext, executor, handler

from examples.enterprise.config import example_deployment
from examples.enterprise.workflow.run import estimator_config
from examples.langgraph.routing.policy import assess_context
from examples.langgraph.routing.retrieval import retrieve_additional_evidence
from examples.langgraph.routing.scenarios import initial_observations
from examples.langgraph.routing.selection import select_context
from omneum import open_stdio_client

from .state import RoutingState


@executor
async def load_evidence(scenario: str, ctx: WorkflowContext[RoutingState]) -> None:
    observations = initial_observations(scenario)
    await ctx.send_message(RoutingState(scenario, len(observations), observations))


@executor
async def evaluate_context(state: RoutingState, ctx: WorkflowContext[RoutingState]) -> None:
    with example_deployment() as (config, server):
        async with open_stdio_client(config, server) as client:
            state.context_evaluation = await client.evaluate_context(
                state.observations,
                estimator=estimator_config(),
            )
    await ctx.send_message(state)


@executor
async def route_context(state: RoutingState, ctx: WorkflowContext[RoutingState]) -> None:
    state.decision = assess_context(state.context_evaluation, retries=state.retry_count)
    state.routing_history = (*state.routing_history, state.decision.route)
    await ctx.send_message(state)


class RetrieveEvidence(Executor):
    def __init__(self, strategy: str):
        super().__init__(id=strategy)
        self.strategy = strategy

    @handler
    async def retrieve(self, state: RoutingState, ctx: WorkflowContext[RoutingState]) -> None:
        additional = retrieve_additional_evidence(
            state.decision.attributes,
            strategy=self.strategy,
            attempt=state.retry_count + 1,
        )
        known_ids = {item.observation_id for item in state.observations}
        new_observations = []
        for item in additional:
            if item.observation_id not in known_ids:
                new_observations.append(item)
                known_ids.add(item.observation_id)
        state.observations = (*state.observations, *new_observations)
        state.retry_count += 1
        await ctx.send_message(state)


@executor
async def select_claims(state: RoutingState, ctx: WorkflowContext[RoutingState]) -> None:
    state.selected_claims = select_context(state.context_evaluation)
    await ctx.send_message(state)


@executor
async def generate_answer(state: RoutingState, ctx: WorkflowContext[None, RoutingState]) -> None:
    state.answer = "\n".join([
        "Application decision: EVALUATION COMPLETE",
        "Selected context:",
        *(f"{claim.attribute}: {claim.value}" for claim in state.selected_claims),
    ])
    await ctx.yield_output(state)


@executor
async def escalate_answer(state: RoutingState, ctx: WorkflowContext[None, RoutingState]) -> None:
    state.answer = (
        "Application decision: ESCALATE\n"
        "Evidence did not meet the routing policy."
    )
    await ctx.yield_output(state)


def build_routing_workflow() -> Workflow:
    builder = WorkflowBuilder(
        start_executor=load_evidence,
        output_from=[generate_answer, escalate_answer],
    )
    builder.add_edge(load_evidence, evaluate_context)
    builder.add_edge(evaluate_context, route_context)
    for strategy in ("retrieve_support", "resolve_conflicts", "diversify_sources"):
        retrieval = RetrieveEvidence(strategy)
        builder.add_edge(
            route_context, retrieval,
            condition=lambda state, route=strategy: state.decision.route == route,
        )
        builder.add_edge(retrieval, evaluate_context)
    builder.add_edge(
        route_context, select_claims,
        condition=lambda state: state.decision.route == "generate",
    )
    builder.add_edge(
        route_context, escalate_answer,
        condition=lambda state: state.decision.route == "escalate",
    )
    builder.add_edge(select_claims, generate_answer)
    return builder.build()

