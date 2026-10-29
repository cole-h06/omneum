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

        generation = result["generation"]
        assert generation["prepared_context"]["context"] in result["answer"]
        assert generation["query_diagnostics"]["relevance_source"] == "bm25"

        assert "Selected context:" in result["answer"]

    asyncio.run(run())
