import asyncio

from examples.context_output import run_cli
from .tools import run_agent


async def execute(options, args, scenario):
    if args.inspect_context:
        return await run_agent(preparation=options, inspect_context=True)
    return await run_agent(question=input("Question: "), preparation=options)


async def main() -> None:
    await run_cli("microsoft", execute, routing=False, debug_json=DEBUG_JSON)


DEBUG_JSON = False

if __name__ == "__main__":
    asyncio.run(main())
