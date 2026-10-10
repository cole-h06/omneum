import argparse
import asyncio

from examples.enterprise.workflow.run import QUESTION
from examples.langgraph.routing.graph import build_routing_graph
from examples.langgraph.routing.policy import assess_context
from examples.langgraph.routing.scenarios import initial_observations


SCENARIOS = (
    "diversify_sources",
    "retrieve_support",
    "resolve_conflicts",
)


async def run_scenario(scenario: str) -> None:
    initial = initial_observations(scenario)

    graph = build_routing_graph(preloaded=True)

    result = await graph.ainvoke({
        "question": QUESTION,
        "observation_batches": [],
        "observations": initial,
        "retry_count": 0,
        "routing_history": (),
    })

    evaluation = result["context_evaluation"]
    decision = assess_context(
        evaluation,
        retries=result["retry_count"],
    )

    print(f"\n=== {scenario} ===")
    print(f"Observations: {len(initial)} -> {len(result['observations'])}")
    print(f"Routing: {' -> '.join(result['routing_history'])} -> {decision.route}")
    print(f"Retries: {result['retry_count']}")

    print("\nClaim support:")
    for claim in sorted(
        evaluation.claim_support,
        key=lambda item: (item.claim.attribute, -item.support),
    ):
        print(
            f"  {claim.claim.attribute}: {claim.claim.value}"
            f" | support={claim.support:.4f}"
            f" | independent={claim.estimated_independent_support_count:.3f}"
        )

    print("\nAnswer:")
    print(result["answer"])


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="LangGraph conditional routing with Omneum."
    )
    parser.add_argument(
        "--scenario",
        choices=(*SCENARIOS, "all"),
        default="all",
    )
    args = parser.parse_args()

    scenarios = SCENARIOS if args.scenario == "all" else (args.scenario,)

    for scenario in scenarios:
        await run_scenario(scenario)


if __name__ == "__main__":
    asyncio.run(main())
