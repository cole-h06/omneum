import asyncio

from examples.context_output import print_routing_status, run_cli
from examples.enterprise.workflow.run import QUESTION
from .graph import build_routing_graph
from .policy import assess_context
from .scenarios import initial_observations


SCENARIOS = ("diversify_sources", "retrieve_support", "resolve_conflicts")


async def run_scenario(scenario: str) -> None:
    from argparse import Namespace
    from examples.context_preparation import PreparationOptions

    _, answer = await execute(PreparationOptions(), Namespace(json=False, compare=False), scenario)
    print(answer)


async def execute(options, args, scenario):
    initial = initial_observations(scenario)
    state = await build_routing_graph(preloaded=True).ainvoke({
        "question": QUESTION, "observation_batches": [], "observations": initial,
        "retry_count": 0, "routing_history": (), "preparation": options,
    })
    if not args.json and not args.compare:
        print_routing_status(scenario, len(initial), state["observations"], (*state["routing_history"], assess_context(state["context_evaluation"], retries=state["retry_count"]).route), state["retry_count"], state["context_evaluation"])
    return state.get("generation"), state["answer"]


async def main() -> None:
    await run_cli("langgraph", execute, routing=True, debug_json=DEBUG_JSON)


DEBUG_JSON = False

if __name__ == "__main__":
    asyncio.run(main())
