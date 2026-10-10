"""End-to-end routing and context selection."""

import asyncio

import pytest

from examples.langgraph.routing.graph import build_routing_graph
from examples.langgraph.routing.policy import REQUIRED_ATTRIBUTES
from examples.langgraph.routing.scenarios import initial_observations


@pytest.mark.parametrize(
    "scenario",
    ("retrieve_support", "resolve_conflicts", "diversify_sources"),
)
def test_routing_and_selection(scenario):
    async def run():
        initial = initial_observations(scenario)

        result = await build_routing_graph(preloaded=True).ainvoke({
            "question": "Evaluate the EU Customer Support Copilot deployment.",
            "observation_batches": [],
            "observations": initial,
            "retry_count": 0,
            "routing_history": (),
        })

        selected = result["selected_claims"]
        values = {claim.attribute: claim.value for claim in selected}

        assert result["routing_history"]
        assert result["retry_count"] >= 1
        assert set(values) == set(REQUIRED_ATTRIBUTES)

        assert values == {
            "input_data_policy": "redacted customer content only",
            "provider_retention": "0 days",
            "processing_region": "EU",
        }

        assert "unredacted customer content allowed" not in result["answer"]
        assert "30 days" not in result["answer"]
        assert "processing_region: US" not in result["answer"]
        assert "Selected context:" in result["answer"]

    asyncio.run(run())
