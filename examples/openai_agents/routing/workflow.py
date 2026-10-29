"""Application-owned branches; SDK-owned function schemas and tool invocation."""

import json

from agents import Agent, FunctionTool, RunContextWrapper, Runner, function_tool
from agents.tool_context import ToolContext

from examples.context_preparation import PreparationOptions, collect_chunks, prepare_generation
from examples.enterprise.config import example_deployment
from examples.enterprise.workflow.run import estimator_config
from examples.langgraph.routing.policy import RoutingPolicy, assess_context
from examples.langgraph.routing.retrieval import retrieve_additional_evidence
from examples.langgraph.routing.scenarios import initial_observations
from examples.langgraph.routing.selection import select_context
from omneum import open_stdio_client

from .state import RoutingState


@function_tool(failure_error_function=None)
async def prepare_context(ctx: RunContextWrapper[RoutingState]) -> str:
    """Return selected original passages and source references for generation."""
    state = ctx.context
    state.generation = await prepare_generation(
        state.observations, question=state.question, estimator=estimator_config(),
        chunks=state.retrieved_chunks, evaluation=state.context_evaluation,
        preparation=state.preparation,
    )
    return state.generation["messages"][1]["content"]


@function_tool(failure_error_function=None)
async def evaluate_context(ctx: RunContextWrapper[RoutingState]) -> str:
    """Evaluate the accumulated observations through Omneum MCP stdio."""
    state = ctx.context
    state.retrieved_chunks = collect_chunks(state.observations)
    with example_deployment() as (config, server):
        async with open_stdio_client(config, server) as client:
            state.context_evaluation = await client.evaluate_context(
                state.observations, estimator=estimator_config(),
            )
    return "Context evaluated."


@function_tool(failure_error_function=None)
async def retrieve_evidence(
    ctx: RunContextWrapper[RoutingState], strategy: str,
) -> str:
    """Retrieve evidence for the application-selected strategy and attributes."""
    state = ctx.context
    if state.decision is None or strategy != state.decision.route:
        raise ValueError("Retrieval strategy must match the application decision")
    additional = retrieve_additional_evidence(
        state.decision.attributes,
        strategy=strategy,
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
    return f"Added {len(new_observations)} observations."


async def invoke_tool(
    tool: FunctionTool, context: RunContextWrapper[RoutingState], **arguments,
) -> str:
    """Invoke the SDK JSON-validation path without entering a model runner."""
    payload = json.dumps(arguments)
    state = context.context
    tool_context = ToolContext.from_agent_context(
        context,
        tool_call_id=f"routing-{len(state.tool_history) + 1}",
        tool_name=tool.name,
        tool_arguments=payload,
    )
    result = await tool.on_invoke_tool(tool_context, payload)
    state.tool_history = (*state.tool_history, tool.name)
    return result


async def run_routing(
    scenario: str, *, policy: RoutingPolicy = RoutingPolicy(),
    preparation: PreparationOptions | None = None, generation_agent: Agent | None = None,
) -> RoutingState:
    observations = initial_observations(scenario)
    state = RoutingState(scenario, len(observations), observations)
    state.preparation = preparation or PreparationOptions()
    context = RunContextWrapper(state)

    while True:
        await invoke_tool(evaluate_context, context)
        state.decision = assess_context(
            state.context_evaluation, retries=state.retry_count, policy=policy,
        )
        state.routing_history = (*state.routing_history, state.decision.route)
        if state.decision.route == "generate":
            state.selected_claims = select_context(state.context_evaluation, policy=policy)
            model_input = await invoke_tool(prepare_context, context)
            state.answer = (
                "Application decision: EVALUATION COMPLETE\nSelected context:\n" + model_input
            )
            if generation_agent is not None:
                result = await Runner.run(generation_agent, state.generation["messages"], context=state)
                state.answer = result.final_output
            return state
        if state.decision.route == "escalate":
            state.answer = (
                "Application decision: ESCALATE\n"
                "Evidence did not meet the routing policy."
            )
            return state
        await invoke_tool(retrieve_evidence, context, strategy=state.decision.route)
