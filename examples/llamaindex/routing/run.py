import asyncio

from examples.context_output import print_routing_status, run_cli
from .workflow import RoutingWorkflow


SCENARIOS = ("diversify_sources", "retrieve_support", "resolve_conflicts")


async def run_scenario(scenario: str) -> None:
    from argparse import Namespace
    from examples.context_preparation import PreparationOptions

    _, answer = await execute(PreparationOptions(), Namespace(json=False, compare=False), scenario)
    print(answer)


async def execute(options, args, scenario):
    state = await RoutingWorkflow(timeout=60, verbose=False, preparation=options).run(scenario=scenario)
    if not args.json and not args.compare:
        print_routing_status(scenario, state.initial_observation_count, state.observations, state.routing_history, state.retry_count, state.context_evaluation)
    return state.generation, state.answer


async def main() -> None:
    await run_cli("llamaindex", execute, routing=True, debug_json=DEBUG_JSON)


DEBUG_JSON = False

if __name__ == "__main__":
    asyncio.run(main())
