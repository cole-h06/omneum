import asyncio

from examples.enterprise.workflow.run import QUESTION

from .graph import build_graph


async def main() -> None:
    graph = build_graph()
    result = await graph.ainvoke(
        {
            "question": QUESTION,
            "observation_batches": [],
        }
    )
    print(result["answer"])


if __name__ == "__main__":
    asyncio.run(main())