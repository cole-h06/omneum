import asyncio

from .agent import agent


async def main() -> None:
    question = input("Question: ")

    result = await agent.run(question)

    print(result.text)


if __name__ == "__main__":
    asyncio.run(main())