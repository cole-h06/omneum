"""Native CrewAI routing, selection, and retry behavior."""

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("crewai")

from examples.crewai.routing.flow import RoutingFlow
from examples.crewai.flow import EnterpriseFlow
from examples.crewai.routing import flow as routing
from examples.crewai.routing.run import SCENARIOS, run_scenario
from examples.langgraph.routing.policy import REQUIRED_ATTRIBUTES, RoutingPolicy
from examples.langgraph.routing.retrieval import ROUTING_VALUES
from examples.langgraph.routing.scenarios import initial_observations
from examples.langgraph.routing.selection import select_context


def test_basic_crewai_flow(example_daemon):
    async def run():
        flow = EnterpriseFlow(tracing=False, suppress_flow_events=True)
        answer = await flow.kickoff_async()
        assert len(flow.state.observations) == 17
        assert len(flow.state.context_evaluation.claim_support) == 6
        assert "Omneum Evaluation" in answer
        assert "Application decision: EVALUATION COMPLETE" in answer

    asyncio.run(run())


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_routing_scenario(scenario, example_daemon):
    async def run():
        flow = RoutingFlow(tracing=False, suppress_flow_events=True)
        answer = await flow.kickoff_async(inputs={"scenario": scenario})
        state = flow.state

        assert state.initial_observation_count == len(initial_observations(scenario))
        assert len(state.observations) > state.initial_observation_count
        assert state.routing_history[0] == scenario
        assert state.routing_history[-1] == "generate"
        assert state.retry_count == len(state.routing_history) - 1
        assert 1 <= state.retry_count <= RoutingPolicy().max_retries
        assert state.decision.route == "generate"
        assert state.context_evaluation.evaluation_latency_ms is not None
        assert state.selected_claims == select_context(state.context_evaluation)
        assert {claim.attribute: claim.value for claim in state.selected_claims} == ROUTING_VALUES
        assert all(
            claim.independent_support >= RoutingPolicy().min_independent_support
            for claim in state.selected_claims
        )
        assert answer == state.answer
        assert answer == "\n".join([
            "Application decision: EVALUATION COMPLETE",
            "Selected context:",
            *(f"{attribute}: {ROUTING_VALUES[attribute]}" for attribute in REQUIRED_ATTRIBUTES),
        ])
        assert "unredacted customer content allowed" not in answer
        assert "30 days" not in answer
        assert "processing_region: US" not in answer

    asyncio.run(run())


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_retry_limit(scenario, example_daemon, monkeypatch):
    calls = []

    def no_evidence(attributes, *, strategy, attempt):
        calls.append((attributes, strategy, attempt))
        return ()

    monkeypatch.setattr(routing, "retrieve_additional_evidence", no_evidence)

    async def run():
        flow = RoutingFlow(tracing=False, suppress_flow_events=True)
        answer = await flow.kickoff_async(inputs={"scenario": scenario})
        state = flow.state
        assert state.routing_history == (scenario, scenario, "escalate")
        assert state.retry_count == RoutingPolicy().max_retries
        assert len(state.observations) == state.initial_observation_count
        assert state.decision.route == "escalate"
        assert state.selected_claims == ()
        assert "ESCALATE" in answer
        assert "EVALUATION COMPLETE" not in answer
        assert [call[1:] for call in calls] == [(scenario, 1), (scenario, 2)]
        assert all(call[0] == state.decision.attributes for call in calls)

    asyncio.run(run())


@pytest.mark.parametrize("strategy", SCENARIOS)
def test_retrieval_targets_decision_and_deduplicates(strategy, monkeypatch):
    flow = RoutingFlow(tracing=False, suppress_flow_events=True)
    existing = initial_observations(strategy)
    flow.state.observations = existing
    flow.state.decision = routing.assess_context(SimpleNamespace(claim_support=()))
    calls = []

    def duplicate_evidence(attributes, *, strategy, attempt):
        calls.append((attributes, strategy, attempt))
        return existing

    monkeypatch.setattr(routing, "retrieve_additional_evidence", duplicate_evidence)
    flow._retrieve(strategy)
    assert flow.state.observations == existing
    assert flow.state.retry_count == 1
    assert calls == [(REQUIRED_ATTRIBUTES, strategy, 1)]


def test_route_and_selection_reject_weak_and_conflicting_claims():
    def claim(attribute, value, support, independent):
        return SimpleNamespace(
            claim=SimpleNamespace(attribute=attribute, value=value),
            support=support,
            estimated_independent_support_count=independent,
            supporting_source_count=2,
        )

    evaluation = SimpleNamespace(claim_support=(
        claim("input_data_policy", "redacted", 1.0, 2.0),
        claim("input_data_policy", "unredacted", 0.9, 2.0),
        claim("provider_retention", "0 days", 1.0, 1.0),
        claim("processing_region", "EU", 2.0, 2.0),
        claim("processing_region", "US", 0.5, 1.0),
    ))
    decision = routing.assess_context(evaluation)
    assert decision.route == "resolve_conflicts"
    assert decision.attributes == ("input_data_policy",)
    selected = select_context(evaluation)
    assert [(item.attribute, item.value) for item in selected] == [("processing_region", "EU")]


def test_terminal_results(example_daemon, capsys):
    asyncio.run(run_scenario("diversify_sources"))
    output = capsys.readouterr().out
    for expected in (
        "=== diversify_sources ===", "Observations: 17 -> 18",
        "Routing: diversify_sources -> generate", "Retries: 1",
        "support=", "independent=", "Selected context:",
        "Application decision: EVALUATION COMPLETE",
    ):
        assert expected in output
