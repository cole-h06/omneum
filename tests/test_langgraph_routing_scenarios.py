"""End-to-end tests for Omneum-driven LangGraph routing."""

import asyncio

import pytest

from examples.langgraph.routing.graph import build_routing_graph
from examples.langgraph.routing.policy import assess_context
from examples.langgraph.routing.scenarios import initial_observations


@pytest.mark.parametrize(
    ("scenario", "expected_first_route"),
    [
        ("diversify_sources", "diversify_sources"),
        ("retrieve_support", "retrieve_support"),
        ("resolve_conflicts", "resolve_conflicts"),
    ],
)
def test_routing_scenario(scenario, expected_first_route):
    async def run():
        initial = initial_observations(scenario)

        result = await build_routing_graph(preloaded=True).ainvoke({
            "question": "Evaluate the EU Customer Support Copilot deployment.",
            "observation_batches": [],
            "observations": initial,
            "retry_count": 0,
            "routing_history": (),
        })

        history = result["routing_history"]
        decision = assess_context(
            result["context_evaluation"],
            retries=result["retry_count"],
        )

        assert history
        assert history[0] == expected_first_route
        assert result["retry_count"] <= 2
        assert len(result["observations"]) > len(initial)
        assert decision.route == "generate", (
            f"{scenario}: {history}, {decision}"
        )
        assert "Application decision: EVALUATION COMPLETE" in result["answer"]

    asyncio.run(run())
