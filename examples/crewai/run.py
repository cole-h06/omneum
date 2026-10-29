import asyncio

from examples.context_output import run_cli
from .flow import EnterpriseFlow


async def execute(options, args, scenario):
    flow = EnterpriseFlow(tracing=False, suppress_flow_events=True, preparation=options)
    await flow.kickoff_async()
    return flow.state.generation, flow.state.answer


async def main() -> None:
    await run_cli("crewai", execute, routing=False, debug_json=DEBUG_JSON)


DEBUG_JSON = False

if __name__ == "__main__":
    asyncio.run(main())
