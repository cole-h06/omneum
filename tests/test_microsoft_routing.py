import asyncio
import importlib
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

pytest.importorskip("agent_framework")

from agent_framework import Agent, Executor, Workflow
from agent_framework.openai import OpenAIChatClient

from examples.langgraph.routing.policy import REQUIRED_ATTRIBUTES, RoutingPolicy
from examples.langgraph.routing.retrieval import ROUTING_VALUES
from examples.langgraph.routing.scenarios import initial_observations
from examples.langgraph.routing.selection import select_context
from examples.microsoft.routing import workflow as routing
from examples.microsoft.routing.run import SCENARIOS


def execute(scenario):
    async def run():
        workflow = routing.build_routing_workflow()
        assert isinstance(workflow, Workflow)
        assert all(isinstance(item, Executor) for item in workflow.get_executors_list())
        result = await workflow.run(scenario)
        assert len(result.get_outputs()) == 1
        invoked = [event.executor_id for event in result if event.type == "executor_invoked"]
        return result.get_outputs()[0], invoked

    return asyncio.run(run())


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_scenarios_native_transitions_and_reevaluation(scenario, example_daemon, monkeypatch):
    evaluations = []
    open_client = routing.open_stdio_client

    @asynccontextmanager
    async def record_client(*args):
        async with open_client(*args) as client:
            async def evaluate(observations, **kwargs):
                result = await client.evaluate_context(observations, **kwargs)
                evaluations.append((observations, result))
                return result
            yield SimpleNamespace(evaluate_context=evaluate)

    monkeypatch.setattr(routing, "open_stdio_client", record_client)
    state, invoked = execute(scenario)
    assert state.initial_observation_count == len(initial_observations(scenario))
    assert len(state.observations) > state.initial_observation_count
    assert state.routing_history[0] == scenario
    assert state.routing_history[-1] == state.decision.route == "generate"
    assert state.retry_count == len(state.routing_history) - 1
    assert 1 <= state.retry_count <= RoutingPolicy().max_retries
    assert len(evaluations) == state.retry_count + 1
    assert len(evaluations[0][0]) == state.initial_observation_count
    assert evaluations[-1][0] == state.observations
    assert all(result.evaluation_latency_ms is not None for _, result in evaluations)
    expected = ["load_evidence"]
    for route in state.routing_history[:-1]:
        expected.extend(["evaluate_context", "route_context", route])
    expected.extend(["evaluate_context", "route_context", "select_claims", "generate_answer"])
    assert invoked == expected
    assert state.selected_claims == select_context(state.context_evaluation)
    assert {claim.attribute: claim.value for claim in state.selected_claims} == ROUTING_VALUES
    assert all(claim.independent_support >= RoutingPolicy().min_independent_support for claim in state.selected_claims)
    assert state.answer == "\n".join([
        "Application decision: EVALUATION COMPLETE", "Selected context:",
        *(f"{attribute}: {ROUTING_VALUES[attribute]}" for attribute in REQUIRED_ATTRIBUTES),
    ])
    for conflicting in ("unredacted customer content allowed", "30 days", "processing_region: US"):
        assert conflicting not in state.answer
    if scenario == "resolve_conflicts":
        assert {item.claim.value for item in state.context_evaluation.claim_support} >= {
            "US", "30 days", "unredacted customer content allowed",
        }
    if scenario == "retrieve_support":
        assert state.retry_count == 2


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_retry_exhaustion_and_escalation(scenario, example_daemon, monkeypatch):
    calls = []

    def no_evidence(attributes, *, strategy, attempt):
        calls.append((attributes, strategy, attempt))
        return ()

    monkeypatch.setattr(routing, "retrieve_additional_evidence", no_evidence)
    state, invoked = execute(scenario)
    assert state.routing_history == (scenario, scenario, "escalate")
    assert state.retry_count == RoutingPolicy().max_retries
    assert len(state.observations) == state.initial_observation_count
    assert state.decision.route == "escalate"
    assert state.selected_claims == ()
    assert "ESCALATE" in state.answer
    assert "EVALUATION COMPLETE" not in state.answer
    assert [call[1:] for call in calls] == [(scenario, 1), (scenario, 2)]
    assert all(call[0] == state.decision.attributes for call in calls)
    assert invoked == [
        "load_evidence", "evaluate_context", "route_context", scenario,
        "evaluate_context", "route_context", scenario,
        "evaluate_context", "route_context", "escalate_answer",
    ]


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_retrieval_targets_and_deduplicates(scenario, example_daemon, monkeypatch):
    retrieve = routing.retrieve_additional_evidence
    calls = []

    def duplicate_evidence(attributes, *, strategy, attempt):
        calls.append((attributes, strategy, attempt))
        additional = retrieve(attributes, strategy=strategy, attempt=attempt)
        return (*initial_observations(scenario), *additional, *additional)

    monkeypatch.setattr(routing, "retrieve_additional_evidence", duplicate_evidence)
    state, _ = execute(scenario)
    assert len({item.observation_id for item in state.observations}) == len(state.observations)
    assert state.decision.route == "generate"
    assert [call[2] for call in calls] == list(range(1, state.retry_count + 1))
    assert all(call[0] and set(call[0]) <= set(REQUIRED_ATTRIBUTES) for call in calls)
    if scenario == "retrieve_support":
        assert calls[0][0] == ("processing_region",)


def test_selection_excludes_unresolved_conflicts_and_weak_support():
    def claim(attribute, value, support, independent):
        return SimpleNamespace(
            claim=SimpleNamespace(attribute=attribute, value=value), support=support,
            estimated_independent_support_count=independent, supporting_source_count=2,
        )

    evaluation = SimpleNamespace(claim_support=(
        claim("input_data_policy", "redacted", 1.0, 2.0),
        claim("input_data_policy", "unredacted", 0.9, 2.0),
        claim("provider_retention", "0 days", 1.0, 1.0),
        claim("processing_region", "EU", 2.0, 2.0),
        claim("processing_region", "US", 0.5, 1.0),
    ))
    assert routing.assess_context(evaluation).route == "resolve_conflicts"
    assert [(item.attribute, item.value) for item in select_context(evaluation)] == [("processing_region", "EU")]


def test_basic_agent_mapping_and_mcp_regression(example_daemon, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-unused")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.5")
    basic = importlib.import_module("examples.microsoft.agent")
    assert isinstance(basic.agent, Agent)
    assert isinstance(basic.agent.client, OpenAIChatClient)
    assert basic.agent.name == "Enterprise AI Assistant"
    assert [tool.name for tool in basic.agent.default_options["tools"]] == ["evaluate_context"]
    assert "evaluate_context tool" in basic.agent.default_options["instructions"]
    captured = []
    render = basic.render_result

    def capture(result):
        captured.append(result)
        return render(result)

    monkeypatch.setattr(basic, "render_result", capture)
    report = asyncio.run(basic.evaluate_context())
    assert len(basic.collect_observations()) == 17
    assert len(captured) == 1
    result = captured[0]
    assert len(result.source_reliability) == 6
    assert len(result.claim_support) == 6
    assert len(result.pairwise_dependencies) == 15
    assert result.evaluation_latency_ms is not None
    assert report == render(result)
    assert "Omneum Evaluation" in report
    assert "Application decision: EVALUATION COMPLETE" in report

    async def direct_evaluation():
        with basic.example_deployment() as (config, server):
            async with basic.open_stdio_client(config, server) as client:
                return await client.evaluate_context(
                    basic.collect_observations(), estimator=basic.estimator_config(),
                )

    direct = asyncio.run(direct_evaluation())
    assert result.claim_support == direct.claim_support
    assert result.source_reliability == direct.source_reliability
    assert result.pairwise_dependencies == direct.pairwise_dependencies


@pytest.mark.parametrize("scenario", (*SCENARIOS, "all"))
def test_cli_without_openai(scenario, example_daemon, monkeypatch, capsys):
    from examples.microsoft.routing import run

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.setattr("sys.argv", ["run", "--scenario", scenario])
    asyncio.run(run.main())
    output = capsys.readouterr().out
    scenarios = SCENARIOS if scenario == "all" else (scenario,)
    for name in scenarios:
        assert f"=== {name} ===" in output
    assert output.count("Application decision: EVALUATION COMPLETE") == len(scenarios)
    assert "Observations:" in output
    assert "Routing:" in output
    assert "Retries:" in output
    assert "Claim support:" in output
    assert "independent=" in output
    assert "Selected context:" in output
