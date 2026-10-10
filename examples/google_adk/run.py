import asyncio

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from examples.enterprise.workflow.run import QUESTION

from .agent import build_agent


async def main() -> None:
    sessions = InMemorySessionService()
    session = await sessions.create_session(app_name="omneum_enterprise", user_id="example")
    runner = Runner(agent=build_agent(), app_name=session.app_name, session_service=sessions)
    try:
        async for event in runner.run_async(
            user_id=session.user_id,
            session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text=QUESTION)]),
        ):
            if event.is_final_response() and event.content:
                print("".join(part.text or "" for part in event.content.parts or []))
    finally:
        await runner.close()


if __name__ == "__main__":
    asyncio.run(main())
