import os

from anthropic import AsyncAnthropic


DEFAULT_MODEL = os.environ.get(
    "ANTHROPIC_MODEL",
    "claude-sonnet-4-20250514",
)


def anthropic_client():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY must be set to run LLM benchmark tracks"
        )

    return AsyncAnthropic()


async def generate(prompt, *, model=None, max_tokens=1024):
    import time

    client = anthropic_client()
    selected_model = model or DEFAULT_MODEL

    started = time.perf_counter()

    response = await client.messages.create(
        model=selected_model,
        max_tokens=max_tokens,
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
    )

    latency_seconds = time.perf_counter() - started

    text = "".join(
        block.text
        for block in response.content
        if block.type == "text"
    )

    return {
        "text": text,
        "model": selected_model,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "latency_seconds": latency_seconds,
    }
