from agent_framework import Agent
from agent_framework.openai import OpenAIChatClient

from .tools import evaluate_context


agent = Agent(
    client=OpenAIChatClient(),
    name="Enterprise AI Assistant",
    instructions=(
        "Answer deployment-readiness questions using the "
        "evaluate_context tool with the user's question before answering. "
        "Use its original passages as evidence, cite chunk IDs, and explain conflicts."
    ),
    tools=[evaluate_context],
)