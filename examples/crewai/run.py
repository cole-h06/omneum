import asyncio

from examples.enterprise.workflow.run import QUESTION

from .flow import EnterpriseFlow


async def main() -> None:
    flow = EnterpriseFlow()
    answer = await flow.kickoff_async(
        inputs={
            "question": QUESTION,
        }
    )
    print(answer)


if __name__ == "__main__":
    asyncio.run(main())