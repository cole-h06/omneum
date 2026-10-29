import asyncio

from examples.context_output import run_cli
from .workflow import EnterpriseWorkflow


async def execute(options, args, scenario):
    workflow = EnterpriseWorkflow(timeout=60, verbose=False, preparation=options)
    handler = workflow.run()
    answer = await handler
    return await handler.ctx.store.get("generation"), answer


async def main() -> None:
    await run_cli("llamaindex", execute, routing=False, debug_json=DEBUG_JSON)


DEBUG_JSON = False

if __name__ == "__main__":
    asyncio.run(main())
