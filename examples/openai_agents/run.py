import asyncio

from agents import Runner

from examples.enterprise.workflow.run import QUESTION

from .agent import agent


async def main():
    result = await Runner.run(
        agent,
        QUESTION,
    )
    print(result.final_output)


if __name__ == "__main__":
    asyncio.run(main())