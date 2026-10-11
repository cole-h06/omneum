"""Tests for Omneum-driven claim selection."""

import asyncio

from examples.langgraph.routing.scenarios import initial_observations
from examples.langgraph.routing.selection import select_context
from examples.langgraph.routing.selection_graph import build_selection_graph


def test_context_selection(example_daemon):
    async def run():
        result = await build_selection_graph().ainvoke({
            "question": "Evaluate the EU Customer Support Copilot deployment.",
            "observation_batches": [],
            "observations": initial_observations("diversify_sources"),
        })

        selected = result["selected_claims"]
        attributes = {claim.attribute for claim in selected}

        assert len(selected) == len(attributes)
        assert all(claim.independent_support >= 1.9 for claim in selected)

        assert "unredacted customer content allowed" not in result["answer"]
        assert "30 days" not in result["answer"]
        assert "US" not in result["answer"]

        assert "Selected context:" in result["answer"]

    asyncio.run(run())
