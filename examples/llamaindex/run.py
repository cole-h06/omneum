import asyncio

from .workflow import EnterpriseWorkflow


async def main() -> None:
    workflow = EnterpriseWorkflow(
        timeout=30,
        verbose=False,
    )
    answer = await workflow.run()
    print(answer)


if __name__ == "__main__":
    asyncio.run(main())