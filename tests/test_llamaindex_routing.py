"""Native LlamaIndex transitions, real MCP evaluation, selection, and retries."""

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("llama_index.core.workflow")

from llama_index.core.workflow import StopEvent, Workflow

from examples.llamaindex import workflow as basic
from examples.llamaindex.routing import workflow as routing
from examples.llamaindex.routing.run import SCENARIOS, run_scenario
from examples.llamaindex.routing.state import RoutingState
from examples.llamaindex.routing.workflow import RoutingWorkflow
from examples.langgraph.routing.policy import REQUIRED_ATTRIBUTES, RoutingPolicy
from examples.langgraph.routing.retrieval import ROUTING_VALUES
from examples.langgraph.routing.scenarios import initial_observations
from examples.langgraph.routing.selection import select_context


async def execute(scenario):
    workflow = RoutingWorkflow(timeout=60)
    assert isinstance(workflow, Workflow)
    handler = workflow.run(scenario=scenario)
    events = [event async for event in handler.stream_events()]
    return await handler, events


def test_basic_workflow_regression(example_daemon, monkeypatch):
    captured = []
    render = basic.render_result

    def capture(result):
        captured.append(result)
        return render(result)

    monkeypatch.setattr(basic, "render_result", capture)

    async def run():
        workflow = basic.EnterpriseWorkflow(timeout=30)
        evidence = await workflow.retrieve(routing.StartEvent())
        assert isinstance(evidence, basic.RetrievalResultsEvent)
        assert len(evidence.results) == 17
        answer = await workflow.run()
        assert len(captured) == 1
        evaluation = captured[0]
        assert len(evaluation.source_reliability) == 6
        assert len(evaluation.claim_support) == 6
        assert len(evaluation.pairwise_dependencies) == 15
        assert evaluation.evaluation_latency_ms is not None
        assert answer == render(evaluation)
        assert "Omneum Evaluation" in answer
        assert "Application decision: EVALUATION COMPLETE" in answer

    asyncio.run(run())


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_routing_scenario_and_native_transitions(scenario, example_daemon):
    state, events = asyncio.run(execute(scenario))
    assert state.initial_observation_count == len(initial_observations(scenario))
    assert len(state.observations) > state.initial_observation_count
    assert state.routing_history[0] == scenario
    assert state.routing_history[-1] == "generate"
    assert state.retry_count == len(state.routing_history) - 1
    assert 1 <= state.retry_count <= RoutingPolicy().max_retries
    assert state.decision.route == "generate"
    evaluations = [event for event in events if isinstance(event, routing.EvaluatedEvent)]
    assert len(evaluations) == state.retry_count + 1
    assert all(event.state.context_evaluation.evaluation_latency_ms is not None for event in evaluations)
    assert len(evaluations[0].state.observations) == state.initial_observation_count
    assert len(evaluations[-1].state.observations) == len(state.observations)

    branches = {
        "diversify_sources": routing.DiversifySourcesEvent,
        "retrieve_support": routing.RetrieveSupportEvent,
        "resolve_conflicts": routing.ResolveConflictsEvent,
    }
    expected = [routing.EvidenceEvent]
    for route in state.routing_history[:-1]:
        expected.extend([routing.EvaluatedEvent, branches[route], routing.EvidenceEvent])
    expected.extend([routing.EvaluatedEvent, routing.SelectContextEvent, routing.GenerateEvent, StopEvent])
    assert [type(event) for event in events] == expected
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
        assert {item.claim.value for item in state.context_evaluation.claim_support} >= {"US", "30 days", "unredacted customer content allowed"}
    if scenario == "retrieve_support":
        assert state.retry_count == 2


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_retry_exhaustion_and_escalation(scenario, example_daemon, monkeypatch):
    calls = []

    def no_evidence(attributes, *, strategy, attempt):
        calls.append((attributes, strategy, attempt))
        return ()

    monkeypatch.setattr(routing, "retrieve_additional_evidence", no_evidence)
    state, events = asyncio.run(execute(scenario))
    assert state.routing_history == (scenario, scenario, "escalate")
    assert state.retry_count == RoutingPolicy().max_retries
    assert len(state.observations) == state.initial_observation_count
    assert state.decision.route == "escalate"
    assert state.selected_claims == ()
    assert "ESCALATE" in state.answer
    assert "EVALUATION COMPLETE" not in state.answer
    assert [call[1:] for call in calls] == [(scenario, 1), (scenario, 2)]
    assert all(call[0] == state.decision.attributes for call in calls)
    assert sum(isinstance(event, routing.EvaluatedEvent) for event in events) == 3
    assert isinstance(events[-2], routing.EscalateEvent)
    assert isinstance(events[-1], StopEvent)
    assert not any(isinstance(event, routing.GenerateEvent) for event in events)


@pytest.mark.parametrize("strategy", SCENARIOS)
def test_retrieval_targets_attributes_and_deduplicates(strategy, monkeypatch):
    existing = initial_observations(strategy)
    state = RoutingState(scenario=strategy, initial_observation_count=len(existing), observations=existing)
    state.decision = routing.assess_context(SimpleNamespace(claim_support=()))
    calls = []
    additional = routing.retrieve_additional_evidence(REQUIRED_ATTRIBUTES, strategy=strategy)

    def duplicates(attributes, *, strategy, attempt):
        calls.append((attributes, strategy, attempt))
        return (*existing, *additional, *additional)

    monkeypatch.setattr(routing, "retrieve_additional_evidence", duplicates)
    event = RoutingWorkflow()._retrieve(state, strategy)
    assert isinstance(event, routing.EvidenceEvent)
    assert state.observations == (*existing, *additional)
    assert state.retry_count == 1
    assert calls == [(REQUIRED_ATTRIBUTES, strategy, 1)]


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


@pytest.mark.parametrize("scenario,counts,retries,history", [
    ("diversify_sources", "17 -> 18", 1, "diversify_sources -> generate"),
    ("retrieve_support", "11 -> 14", 2, "retrieve_support -> retrieve_support -> generate"),
    ("resolve_conflicts", "9 -> 12", 1, "resolve_conflicts -> generate"),
])
def test_terminal_results(scenario, counts, retries, history, example_daemon, capsys):
    asyncio.run(run_scenario(scenario))
    output = capsys.readouterr().out
    for expected in (
        f"=== {scenario} ===", f"Observations: {counts}", f"Routing: {history}",
        f"Retries: {retries}", "support=", "independent=", "Selected context:",
        "Application decision: EVALUATION COMPLETE",
    ):
        assert expected in output
