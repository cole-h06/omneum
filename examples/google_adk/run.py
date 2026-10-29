import asyncio

from examples.context_output import run_cli
from .agent import run_agent


async def execute(options, args, scenario):
    return await run_agent(preparation=options, inspect_context=args.inspect_context)


async def main() -> None:
    await run_cli("google_adk", execute, routing=False, debug_json=DEBUG_JSON)


DEBUG_JSON = False

if __name__ == "__main__":
    asyncio.run(main())
