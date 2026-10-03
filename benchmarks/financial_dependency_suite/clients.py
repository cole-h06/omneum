import os
import time

from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from google import genai
from openai import AsyncOpenAI


load_dotenv()


DEFAULT_PROVIDER = os.environ.get(
    "LLM_PROVIDER",
    "anthropic",
)

DEFAULT_MODELS = {
    "anthropic": os.environ.get(
        "ANTHROPIC_MODEL",
        "claude-sonnet-5-5",
    ),
    "openai": os.environ.get(
        "OPENAI_MODEL",
        "gpt-6-astra",
    ),
    "google": os.environ.get(
        "GOOGLE_MODEL",
        "gemini-3.8-flash",
    ),
}


def _require_env(name):
    value = os.environ.get(name)

    if not value:
        raise RuntimeError(
            f"{name} must be set to run this LLM benchmark"
        )

    return value


async def _generate_anthropic(prompt, model, max_tokens):
    _require_env("ANTHROPIC_API_KEY")

    started = time.perf_counter()

    async with AsyncAnthropic() as client:
        response = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
        )

    latency = time.perf_counter() - started

    text = "".join(
        block.text
        for block in response.content
        if block.type == "text"
    )

    return {
        "text": text,
        "provider": "anthropic",
        "model": model,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "latency_seconds": latency,
    }


async def _generate_openai(prompt, model, max_tokens):
    _require_env("OPENAI_API_KEY")

    started = time.perf_counter()

    async with AsyncOpenAI() as client:
        response = await client.responses.create(
            model=model,
            input=prompt,
            max_output_tokens=max_tokens,
        )

    latency = time.perf_counter() - started

    usage = response.usage

    return {
        "text": response.output_text,
        "provider": "openai",
        "model": model,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "latency_seconds": latency,
    }


async def _generate_google(prompt, model, max_tokens):
    api_key = _require_env("GEMINI_API_KEY")

    client = genai.Client(api_key=api_key)

    started = time.perf_counter()

    response = await client.aio.models.generate_content(
        model=model,
        contents=prompt,
        config={
            "max_output_tokens": max_tokens,
        },
    )

    latency = time.perf_counter() - started

    usage = response.usage_metadata

    return {
        "text": response.text or "",
        "provider": "google",
        "model": model,
        "input_tokens": usage.prompt_token_count,
        "output_tokens": usage.candidates_token_count,
        "latency_seconds": latency,
    }


async def generate(
    prompt,
    *,
    provider=None,
    model=None,
    max_tokens=1024,
):
    selected_provider = provider or DEFAULT_PROVIDER

    if selected_provider not in DEFAULT_MODELS:
        raise ValueError(
            f"Unsupported LLM provider: {selected_provider}"
        )

    selected_model = (
        model
        or DEFAULT_MODELS[selected_provider]
    )

    if selected_provider == "anthropic":
        return await _generate_anthropic(
            prompt,
            selected_model,
            max_tokens,
        )

    if selected_provider == "openai":
        return await _generate_openai(
            prompt,
            selected_model,
            max_tokens,
        )

    return await _generate_google(
        prompt,
        selected_model,
        max_tokens,
    )
