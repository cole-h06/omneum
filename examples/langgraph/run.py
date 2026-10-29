import asyncio

from examples.context_output import run_cli
from examples.enterprise.workflow.run import QUESTION
from .graph import build_graph


async def execute(options, args, scenario):
    state = await build_graph().ainvoke({
        "question": QUESTION, "observation_batches": [], "preparation": options,
    })
    return state["generation"], state["answer"]


async def main() -> None:
    await run_cli("langgraph", execute, routing=False, debug_json=DEBUG_JSON)


DEBUG_JSON = False

if __name__ == "__main__":
    asyncio.run(main())
