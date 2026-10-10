import argparse
import asyncio

from .workflow import run_routing


SCENARIOS = ("diversify_sources", "retrieve_support", "resolve_conflicts")


async def run_scenario(scenario: str) -> None:
    state = await run_routing(scenario)
    print(f"\n=== {scenario} ===")
    print(f"Observations: {state.initial_observation_count} -> {len(state.observations)}")
    print(f"Routing: {' -> '.join(state.routing_history)}")
    print(f"Retries: {state.retry_count}")
    print("\nClaim support:")
    for item in sorted(
        state.context_evaluation.claim_support,
        key=lambda item: (item.claim.attribute, -item.support),
    ):
        print(
            f"  {item.claim.attribute}: {item.claim.value}"
            f" | support={item.support:.4f}"
            f" | independent={item.estimated_independent_support_count:.3f}"
        )
    if not state.selected_claims:
        print("\nSelected context: (none)")
    print(f"\nAnswer:\n{state.answer}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Google ADK native deterministic routing with Omneum.")
    parser.add_argument("--scenario", choices=(*SCENARIOS, "all"), default="all")
    args = parser.parse_args()
    for scenario in SCENARIOS if args.scenario == "all" else (args.scenario,):
        await run_scenario(scenario)


if __name__ == "__main__":
    asyncio.run(main())
