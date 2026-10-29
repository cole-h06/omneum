import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

pytest.importorskip("google.adk")

from google.adk.agents import BaseAgent, LlmAgent
from google.adk.runners import Runner
from google.adk.tools import FunctionTool
from google.adk.models.google_llm import Gemini

from examples.langgraph.routing.policy import REQUIRED_ATTRIBUTES, RoutingPolicy
from examples.langgraph.routing.retrieval import ROUTING_VALUES
from examples.langgraph.routing.scenarios import initial_observations
from examples.langgraph.routing.selection import select_context
from examples.google_adk.routing import workflow as routing
from examples.google_adk.routing.run import SCENARIOS


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_scenarios_native_runner_and_mcp_reevaluation(scenario, example_daemon, monkeypatch):
    for name in ("GOOGLE_API_KEY", "GEMINI_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS",
                 "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION", "GOOGLE_GENAI_USE_VERTEXAI"):
        monkeypatch.delenv(name, raising=False)
    evaluations = []
    events = []
    open_client = routing.open_stdio_client

    @asynccontextmanager
    async def record_client(*args):
        async with open_client(*args) as client:
            async def evaluate(observations, **kwargs):
                result = await client._evaluate_context(observations, **kwargs)
                evaluations.append((observations, result))
                return result
            yield SimpleNamespace(evaluate_context=evaluate)

    monkeypatch.setattr(routing, "open_stdio_client", record_client)

    async def no_model(*args, **kwargs):
        pytest.fail("Routing must not request a Gemini model")
        yield

    monkeypatch.setattr(Gemini, "generate_content_async", no_model)
    original_run = Runner.run_async

    async def record_run(self, **kwargs):
        assert isinstance(self.agent, routing.RoutingAgent)
        assert isinstance(self.agent, BaseAgent)
        async for event in original_run(self, **kwargs):
            events.append(event)
            yield event
        session = await self.session_service.get_session(
            app_name=self.app_name, user_id=kwargs["user_id"], session_id=kwargs["session_id"],
        )
        assert session.state["answer"] == self.agent.state.answer
        assert session.state["routing_history"] == list(self.agent.state.routing_history)
        assert len(session.events) == len(events) + 1

    monkeypatch.setattr(Runner, "run_async", record_run)
    state = asyncio.run(routing.run_routing(scenario))
    assert state.initial_observation_count == len(initial_observations(scenario))
    assert len(state.observations) > state.initial_observation_count
    assert state.routing_history[0] == scenario
    assert state.routing_history[-1] == state.decision.route == "generate"
    assert state.retry_count == len(state.routing_history) - 1
    assert 1 <= state.retry_count <= RoutingPolicy().max_retries
    assert len(evaluations) == state.retry_count + 1
    assert len(evaluations[0][0]) == state.initial_observation_count
    assert evaluations[-1][0] == state.observations
    initial = evaluations[0][1]
    assert len(select_context(initial)) < len(REQUIRED_ATTRIBUTES)
    if scenario == "diversify_sources":
        assert any(item.dependency > 0 for item in initial.pairwise_dependencies)
    assert all(result.evaluation_latency_ms is not None for _, result in evaluations)
    stages = tuple(event.actions.state_delta["stage"] for event in events if "stage" in event.actions.state_delta)
    expected = ("load_evidence",)
    for route in state.routing_history[:-1]:
        expected += ("evaluate_context", "route_context", route)
    expected += ("evaluate_context", "route_context", "select_context", "generate")
    assert stages == state.stage_history == expected
    assert events[-1].is_final_response()
    assert events[-1].content is None
    assert events[-1].actions.state_delta["generation_input"] == state.generation_content.model_dump(mode="json")
    assert state.selected_claims == select_context(state.context_evaluation)
    assert {claim.attribute: claim.value for claim in state.selected_claims} == ROUTING_VALUES
    assert all(claim.independent_support >= RoutingPolicy().min_independent_support for claim in state.selected_claims)
    assert state.generation["prepared_context"]["context"] in state.generation_content.parts[0].text
    assert state.generation_content.parts[0].text in state.answer
    for chunk in state.generation["retrieved_chunks"]:
        if chunk["chunk_id"] in state.generation["prepared_context"]["packed_chunk_ids"]:
            assert chunk["raw_text"] in state.generation_content.parts[0].text
        else:
            assert chunk["raw_text"] not in state.generation_content.parts[0].text
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
    state = asyncio.run(routing.run_routing(scenario))
    assert state.routing_history == (scenario, scenario, "escalate")
    assert state.retry_count == RoutingPolicy().max_retries
    assert len(state.observations) == state.initial_observation_count
    assert state.selected_claims == ()
    assert "ESCALATE" in state.answer
    assert "EVALUATION COMPLETE" not in state.answer
    assert [call[1:] for call in calls] == [(scenario, 1), (scenario, 2)]
    assert all(call[0] == state.decision.attributes for call in calls)
    assert state.stage_history == (
        "load_evidence", "evaluate_context", "route_context", scenario,
        "evaluate_context", "route_context", scenario,
        "evaluate_context", "route_context", "escalate",
    )


def test_zero_retry_policy_escalates_before_retrieval(example_daemon):
    state = asyncio.run(routing.run_routing("retrieve_support", policy=RoutingPolicy(max_retries=0)))
    assert state.routing_history == ("escalate",)
    assert state.retry_count == 0
    assert state.stage_history == ("load_evidence", "evaluate_context", "route_context", "escalate")
    assert state.selected_claims == ()


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_retrieval_targets_and_deduplicates(scenario, example_daemon, monkeypatch):
    retrieve = routing.retrieve_additional_evidence
    calls = []

    def duplicate_evidence(attributes, *, strategy, attempt):
        calls.append((attributes, strategy, attempt))
        additional = retrieve(attributes, strategy=strategy, attempt=attempt)
        return (*initial_observations(scenario), *additional, *additional)

    monkeypatch.setattr(routing, "retrieve_additional_evidence", duplicate_evidence)
    state = asyncio.run(routing.run_routing(scenario))
    assert len({item.observation_id for item in state.observations}) == len(state.observations)
    assert state.decision.route == "generate"
    assert [call[2] for call in calls] == list(range(1, state.retry_count + 1))
    assert all(call[0] and set(call[0]) <= set(REQUIRED_ATTRIBUTES) for call in calls)
    if scenario == "retrieve_support":
        assert calls[0][0] == ("processing_region",)


def test_unsupported_claims():
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
    assert len(evaluation.claim_support) == 5


def test_enterprise_mapping_and_mcp_regression(example_daemon, monkeypatch):
    from examples.google_adk import agent as basic

    assert isinstance(basic.agent, LlmAgent)
    assert basic.agent.name == "enterprise_assistant"
    assert basic.agent.tools == [basic.evaluation_tool]
    assert isinstance(basic.evaluation_tool, FunctionTool)
    assert "evaluate_context tool" in basic.agent.instruction
    captured = []
    prepare = basic.prepare_generation

    async def capture(*args, **kwargs):
        result = await prepare(*args, **kwargs)
        captured.append(result)
        return result

    monkeypatch.setattr(basic, "prepare_generation", capture)
    model_input = asyncio.run(basic.evaluation_tool.run_async(args={}, tool_context=None))
    assert len(basic.collect_observations()) == 17
    assert len(captured) == 1
    result = captured[0]
    assert model_input == result["messages"][1]["content"]
    assert result["prepared_context"]["context"] in model_input
    assert len(result["prepared_context"]["evaluation"]["source_reliability"]) == 6
    assert len(result["prepared_context"]["evaluation"]["pairwise_dependencies"]) == 15
    assert result["query_diagnostics"]["relevance_source"] == "bm25"
    assert "Source references:" in model_input
    assert "Omneum Evaluation" not in model_input


@pytest.mark.parametrize("scenario", (*SCENARIOS, "all"))
def test_cli_without_gemini(scenario, example_daemon, monkeypatch, capsys):
    from examples.google_adk.routing import run

    for name in ("GOOGLE_API_KEY", "GEMINI_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS",
                 "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION", "GOOGLE_GENAI_USE_VERTEXAI"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("GOOGLE_ADK_MODEL", raising=False)
    monkeypatch.setattr("sys.argv", ["run", "--scenario", scenario])
    asyncio.run(run.main())
    output = capsys.readouterr().out
    scenarios = SCENARIOS if scenario == "all" else (scenario,)
    for name in scenarios:
        assert f"=== {name} ===" in output
    assert output.count("Application decision: EVALUATION COMPLETE") == len(scenarios)
    for field in ("Observations:", "Routing:", "Retries:", "Claim support:", "independent=", "Selected context:"):
        assert field in output


def test_enterprise_model_configuration(monkeypatch):
    from examples.google_adk.agent import build_agent, evaluation_tool

    monkeypatch.setenv("GOOGLE_ADK_MODEL", "gemini-2.5-pro")
    agent = build_agent()
    assert agent.model == "gemini-2.5-pro"
    declaration = evaluation_tool._get_declaration()
    assert declaration.name == "evaluate_context"
    assert declaration.parameters.required == []
    assert declaration.parameters.properties["question"].type.value == "STRING"
    assert declaration.parameters.properties["question"].default == routing.QUESTION


def test_enterprise_runner_tool_round_trip_with_stub_model(example_daemon, monkeypatch, capsys):
    from google.adk.models.llm_response import LlmResponse
    from google.genai import types
    from examples.google_adk.agent import build_agent
    from google.adk.sessions import InMemorySessionService

    requests = []

    async def model_response(self, request, stream=False):
        requests.append(request)
        if len(requests) == 1:
            assert "evaluate_context" in request.tools_dict
            yield LlmResponse(content=types.Content(role="model", parts=[
                types.Part(function_call=types.FunctionCall(name="evaluate_context", args={})),
            ]))
        else:
            responses = [part.function_response for content in request.contents
                         for part in content.parts or [] if part.function_response]
            assert len(responses) == 1
            report = responses[0].response["result"]
            assert "Retrieved context:" in report
            assert '"document"' in report or '"enterprise_controls"' in report
            assert "Omneum Evaluation" not in report
            assert "redacted customer content only" in report
            yield LlmResponse(content=types.Content(role="model", parts=[
                types.Part(text="Test model received original evidence."),
            ]))

    monkeypatch.setattr(Gemini, "generate_content_async", model_response)
    async def run_legacy_tool_agent():
        sessions = InMemorySessionService()
        session = await sessions.create_session(app_name="test", user_id="test")
        runner = Runner(agent=build_agent(), app_name=session.app_name, session_service=sessions)
        try:
            async for event in runner.run_async(user_id=session.user_id, session_id=session.id,
                new_message=types.Content(role="user", parts=[types.Part(text="What are the EU copilot controls?")])):
                if event.is_final_response() and event.content is not None:
                    print("".join(part.text for part in event.content.parts if part.text))
        finally:
            await runner.close()

    asyncio.run(run_legacy_tool_agent())
    assert len(requests) == 2
    assert capsys.readouterr().out.strip() == "Test model received original evidence."
