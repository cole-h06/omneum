import os
from copy import deepcopy
import time

from dotenv import load_dotenv


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

# Gemini's response cap includes internal thinking, not only the selection JSON.
# Keep its default thinking policy; enlarge only the structured-selector limit.
GOOGLE_SELECTION_MAX_OUTPUT_TOKENS = 8192


def _usage_metadata(usage):
    """Return only provider supplied usage fields in JSON-safe form."""
    if usage is None:
        return None
    dump = getattr(usage, "model_dump", None)
    if callable(dump):
        return dump(mode="json", exclude_unset=True)
    if isinstance(usage, dict):
        return usage
    # Lightweight fallback for test doubles; SDK models use model_dump above.
    fields = (
        "input_tokens", "output_tokens", "total_tokens",
        "output_tokens_details", "input_tokens_details",
        "prompt_token_count", "candidates_token_count",
        "thoughts_token_count", "total_token_count",
        "cached_content_token_count", "tool_use_prompt_token_count",
        "prompt_tokens_details", "candidates_tokens_details",
        "cache_tokens_details", "tool_use_prompt_tokens_details",
    )
    return {name: getattr(usage, name) for name in fields
            if hasattr(usage, name)}


def _usage_with_reasoning(usage, reasoning_value):
    """Retain raw provider fields and expose returned reasoning usage uniformly."""
    metadata = _usage_metadata(usage)
    if metadata is None:
        return None
    metadata = dict(metadata)
    metadata["reasoning_tokens"] = reasoning_value
    return metadata


def _require_env(name):
    value = os.environ.get(name)

    if not value:
        raise RuntimeError(
            f"{name} must be set to run this LLM benchmark"
        )

    return value


async def _generate_anthropic(prompt, model, max_tokens, *, response_schema=None, effort=None,
                              max_retries=None, timeout=None):
    from anthropic import AsyncAnthropic

    _require_env("ANTHROPIC_API_KEY")

    started = time.perf_counter()

    output_config = {}
    if response_schema is not None:
        output_config["format"] = {"type": "json_schema", "schema": response_schema}
    if effort is not None:
        output_config["effort"] = effort
    options = {"output_config": output_config} if output_config else {}
    client_options = {} if max_retries is None else {"max_retries": max_retries}
    if timeout is not None:
        client_options["timeout"] = timeout
    async with AsyncAnthropic(**client_options) as client:
        response = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            **options,
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
        "response_diagnostics": {
            "stop_reason": getattr(response, "stop_reason", None),
            "content_block_types": [block.type for block in response.content],
            "usage_metadata": _usage_with_reasoning(
                response.usage,
                getattr(getattr(response.usage, "output_tokens_details", None),
                        "reasoning_tokens", None),
            ),
        },
    }


async def _generate_openai(prompt, model, max_tokens, *, response_schema=None,
                           reasoning_effort=None, max_retries=None, timeout=None):
    from openai import AsyncOpenAI

    _require_env("OPENAI_API_KEY")

    started = time.perf_counter()

    options = {}
    if reasoning_effort is not None:
        options["reasoning"] = {"effort": reasoning_effort}
    if response_schema is not None:
        options["text"] = {"format": {
            "type": "json_schema", "name": "source_selection",
            "strict": True, "schema": response_schema,
        }}
    client_options = {} if max_retries is None else {"max_retries": max_retries}
    if timeout is not None:
        client_options["timeout"] = timeout
    async with AsyncOpenAI(**client_options) as client:
        response = await client.responses.create(
            model=model,
            input=prompt,
            max_output_tokens=max_tokens,
            **options,
        )

    latency = time.perf_counter() - started

    usage = response.usage

    return {
        "text": response.output_text,
        "response_diagnostics": {
            "stop_reason": getattr(response, "status", None),
            "finish_reasons": ([response.incomplete_details.reason]
                               if getattr(response, "incomplete_details", None) else []),
            "content_block_types": [item.type for item in (getattr(response, "output", None) or [])],
            "usage_metadata": _usage_with_reasoning(
                usage,
                getattr(getattr(usage, "output_tokens_details", None),
                        "reasoning_tokens", None),
            ),
        },
        "provider": "openai",
        "model": model,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "latency_seconds": latency,
    }


async def _generate_google(prompt, model, max_tokens, *, response_schema=None, thinking_level=None,
                           retry_attempts=None, timeout=None):
    from google import genai

    if thinking_level is not None and (model != "gemini-3.8-flash" or thinking_level not in {"low", "medium", "high"}):
        raise ValueError("gemini-3.8-flash supports thinking levels low, medium, high")
    api_key = _require_env("GEMINI_API_KEY")

    client_options = {"api_key": api_key}
    if retry_attempts is not None or timeout is not None:
        client_options["http_options"] = genai.types.HttpOptions(
            **({"retry_options": genai.types.HttpRetryOptions(attempts=retry_attempts)}
               if retry_attempts is not None else {}),
            **({"timeout": timeout * 1000} if timeout is not None else {}),
        )
    client = genai.Client(**client_options)

    started = time.perf_counter()

    config = {"max_output_tokens": max_tokens}
    if response_schema is not None:
        if model == "gemini-3.8-flash":
            config["max_output_tokens"] = max(max_tokens, GOOGLE_SELECTION_MAX_OUTPUT_TOKENS)
        config.update(response_mime_type="application/json",
                      response_json_schema=response_schema)
    request_config = deepcopy(config)
    if thinking_level is not None:
        request_config["thinking_config"] = {"thinking_level": thinking_level}
        # google-genai 2.21 emits thinking_level instead of thinkingLevel.
        # Its supported extra_body hook preserves the required REST spelling.
        config["http_options"] = genai.types.HttpOptions(extra_body={
            "generationConfig": {"thinkingConfig": {"thinkingLevel": thinking_level.upper()}}
        })
    response = await client.aio.models.generate_content(
        model=model,
        contents=prompt,
        config=config,
    )

    latency = time.perf_counter() - started

    usage = response.usage_metadata

    return {
        "text": response.text or "",
        "response_diagnostics": {
            "finish_reasons": [
                str(candidate.finish_reason.value)
                if hasattr(candidate.finish_reason, "value")
                else str(candidate.finish_reason)
                for candidate in (getattr(response, "candidates", None) or [])
                if getattr(candidate, "finish_reason", None) is not None
            ],
            "usage_metadata": _usage_with_reasoning(
                usage, getattr(usage, "thoughts_token_count", None),
            ),
            **({"requested_thinking_level": thinking_level,
                "model_version": getattr(response, "model_version", None)} if thinking_level is not None else {}),
        },
        "provider": "google",
        "model": model,
        "input_tokens": usage.prompt_token_count,
        "output_tokens": usage.candidates_token_count,
        "latency_seconds": latency,
        **({"request_parameters": {"model": model, "contents": prompt, "config": request_config}}
           if thinking_level is not None else {}),
    }


async def generate(
    prompt,
    *,
    provider=None,
    model=None,
    max_tokens=1024,
    response_schema=None,
    thinking_level=None,
):
    selected_provider = provider or DEFAULT_PROVIDER
    if thinking_level is not None and selected_provider != "google":
        raise ValueError("thinking_level is supported only for Google requests")

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
            response_schema=response_schema,
        )

    if selected_provider == "openai":
        return await _generate_openai(
            prompt,
            selected_model,
            max_tokens,
            response_schema=response_schema,
        )

    return await _generate_google(
        prompt,
        selected_model,
        max_tokens,
        response_schema=response_schema,
        **({"thinking_level": thinking_level} if thinking_level is not None else {}),
    )
