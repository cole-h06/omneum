import asyncio

from examples.enterprise.workflow.run import QUESTION
from examples.langgraph.routing.graph import build_routing_graph
from examples.langgraph.routing.policy import assess_context


def test_langgraph_routing():
    async def run():
        graph = build_routing_graph()

        result = await graph.ainvoke({
            "question": QUESTION,
            "observation_batches": [],
            "retry_count": 0,
            "routing_history": (),
        })

        assert result["routing_history"] == ("diversify_sources",)
        assert result["retry_count"] == 1
        assert len(result["observations"]) == 18

        decision = assess_context(
            result["context_evaluation"],
            retries=result["retry_count"],
        )

        assert decision.route == "generate"
        assert "Application decision: EVALUATION COMPLETE" in result["answer"]

        claims = {
            (item.claim.attribute, item.claim.value): item
            for item in result["context_evaluation"].claim_support
        }

        assert (
            claims[
                ("input_data_policy", "redacted customer content only")
            ].estimated_independent_support_count
            >= 2.0
        )

    asyncio.run(run())
