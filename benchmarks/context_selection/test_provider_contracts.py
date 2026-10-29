"""Offline SDK/selector contract checks; every HTTP request is intercepted."""

import asyncio
import json

import httpx
import pytest
from anthropic import AsyncAnthropic
from google import genai

from benchmarks.context_selection import clients
from benchmarks.context_selection.application_comparison import _extract_json, SELECTION_SCHEMA


@pytest.mark.parametrize(
    "blocks, expected",
    [
        ([{"type": "text", "text": '{"selected_sources": ["a"]}'}],
         '{"selected_sources": ["a"]}'),
        ([{"type": "text", "text": '{"selected_sources":'},
          {"type": "text", "text": ' ["a"]}'}],
         '{"selected_sources": ["a"]}'),
        ([{"type": "thinking", "thinking": "reasoning", "signature": "sig"},
          {"type": "text", "text": '{"selected_sources": ["a"]}'}],
         '{"selected_sources": ["a"]}'),
        ([], ""),
        ([{"type": "thinking", "thinking": "reasoning", "signature": "sig"}], ""),
        ([{"type": "text", "text": "Here are the sources."}], "Here are the sources."),
    ],
)
@pytest.mark.parametrize("schema", [None, SELECTION_SCHEMA])
@pytest.mark.parametrize("effort", [None, "low"])
def test_anthropic_actual_sdk_extraction(monkeypatch, blocks, expected, schema, effort):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={
            "id": "msg_fixture", "type": "message", "role": "assistant",
            "model": "claude-sonnet-5-5", "content": blocks,
            "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 12, "output_tokens": 9},
        })

    monkeypatch.setenv("ANTHROPIC_API_KEY", "offline-fixture")
    monkeypatch.setattr("anthropic.AsyncAnthropic", lambda: AsyncAnthropic(
        api_key="offline-fixture", base_url="https://offline.invalid",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    ))
    result = asyncio.run(clients._generate_anthropic(
        "frozen prompt", "claude-sonnet-5-5", 1024, response_schema=schema, effort=effort,
    ))
    assert result["text"] == expected
    assert len(requests) == 1
    assert requests[0].url.path == "/v1/messages"
    expected_request = {
        "model": "claude-sonnet-5-5", "max_tokens": 1024,
        "messages": [{"role": "user", "content": "frozen prompt"}],
    }
    output_config = {}
    if schema is not None:
        output_config["format"] = {"type": "json_schema", "schema": schema}
    if effort is not None:
        output_config["effort"] = effort
    if output_config:
        expected_request["output_config"] = output_config
    assert json.loads(requests[0].content) == expected_request
    assert result["input_tokens"] == 12
    assert result["output_tokens"] == 9


@pytest.mark.parametrize("text", ["", "   ", "Here is JSON: {}", '{"selected_sources":'])
def test_malformed_output_is_not_repaired(text):
    with pytest.raises(json.JSONDecodeError):
        _extract_json(text)


def test_existing_code_fence_protocol():
    assert _extract_json('```json\n{"selected_sources": ["a"]}\n```') == {
        "selected_sources": ["a"],
    }


@pytest.mark.parametrize("status", [429, 503])
@pytest.mark.parametrize("schema", [None, SELECTION_SCHEMA])
def test_google_default_does_not_retry(monkeypatch, status, schema):
    attempts = []

    def respond(request):
        attempts.append(request)
        return httpx.Response(status, json={"error": {
            "code": status, "message": "offline fixture",
            "status": "RESOURCE_EXHAUSTED" if status == 429 else "UNAVAILABLE",
        }})

    # Keep the SDK's retry defaults and replace only its HTTP transport.
    real_client = genai.Client
    monkeypatch.setenv("GEMINI_API_KEY", "offline-fixture")
    monkeypatch.setattr(genai, "Client", lambda **kwargs: real_client(
        **kwargs, http_options={
            "base_url": "https://offline.invalid",
            "async_client_args": {"transport": httpx.MockTransport(respond)},
        },
    ))
    with pytest.raises(genai.errors.APIError):
        asyncio.run(clients._generate_google(
            "frozen prompt", "gemini-3.8-flash", 1024, response_schema=schema,
        ))
    assert len(attempts) == 1


@pytest.mark.parametrize("schema", [None, SELECTION_SCHEMA])
@pytest.mark.parametrize("model", ["gemini-3.8-flash", "unchanged-model"])
@pytest.mark.parametrize("max_tokens", [1024, 16384])
def test_google_actual_sdk_schema_request(monkeypatch, schema, model, max_tokens):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={
            "candidates": [{"content": {"role": "model", "parts": [
                {"text": '{"selected_sources":["a"]}'},
            ]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 9,
                              "thoughtsTokenCount": 7, "totalTokenCount": 28},
        })

    real_client = genai.Client
    monkeypatch.setenv("GEMINI_API_KEY", "offline-fixture")
    monkeypatch.setattr(genai, "Client", lambda **kwargs: real_client(
        **kwargs, http_options={"base_url": "https://offline.invalid",
                               "async_client_args": {"transport": httpx.MockTransport(respond)}},
    ))
    result = asyncio.run(clients.generate(
        "frozen prompt", provider="google", model=model, max_tokens=max_tokens, response_schema=schema,
    ))
    assert len(requests) == 1
    assert f"{model}:generateContent" in requests[0].url.path
    config = {"maxOutputTokens": max_tokens}
    if schema is not None:
        if model == "gemini-3.8-flash":
            config["maxOutputTokens"] = max(max_tokens, 8192)
        config.update(responseMimeType="application/json", responseJsonSchema=schema)
    assert json.loads(requests[0].content)["generationConfig"] == config
    assert _extract_json(result["text"]) == {"selected_sources": ["a"]}
    usage = result["response_diagnostics"]["usage_metadata"]
    assert usage["prompt_token_count"] == 12
    assert usage["candidates_token_count"] == 9
    assert usage["thoughts_token_count"] == 7
    assert usage["total_token_count"] == 28
    assert usage["reasoning_tokens"] == 7


@pytest.mark.parametrize("schema", [None, SELECTION_SCHEMA])
@pytest.mark.parametrize("reasoning_effort", [None, "low"])
def test_openai_actual_sdk_schema_request(monkeypatch, schema, reasoning_effort):
    from openai import AsyncOpenAI
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={
            "id": "resp_fixture", "object": "response", "created_at": 0,
            "model": "gpt-6-astra", "status": "completed",
            "output": [{"id": "msg_fixture", "type": "message", "role": "assistant",
                        "status": "completed", "content": [{"type": "output_text",
                        "text": '{"selected_sources":["a"]}', "annotations": []}]}],
            "usage": {"input_tokens": 12, "output_tokens": 9, "total_tokens": 21,
                      "output_tokens_details": {"reasoning_tokens": 4}},
        })

    monkeypatch.setenv("OPENAI_API_KEY", "offline-fixture")
    monkeypatch.setattr("openai.AsyncOpenAI", lambda: AsyncOpenAI(
        api_key="offline-fixture", base_url="https://offline.invalid",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    ))
    result = asyncio.run(clients._generate_openai(
        "frozen prompt", "gpt-6-astra", 1024, response_schema=schema,
        reasoning_effort=reasoning_effort,
    ))
    expected = {"model": "gpt-6-astra", "input": "frozen prompt", "max_output_tokens": 1024}
    if schema is not None:
        expected["text"] = {"format": {"type": "json_schema", "name": "source_selection",
                                        "strict": True, "schema": schema}}
    if reasoning_effort is not None:
        expected["reasoning"] = {"effort": reasoning_effort}
    assert len(requests) == 1
    assert json.loads(requests[0].content) == expected
    assert _extract_json(result["text"]) == {"selected_sources": ["a"]}
    assert result["response_diagnostics"]["usage_metadata"]["reasoning_tokens"] == 4


def test_google_unreturned_thinking_usage_is_null(monkeypatch):
    def respond(request):
        return httpx.Response(200, json={
            "candidates": [{"content": {"role": "model", "parts": [{
                "text": '{"selected_sources":["a"]}',
            }]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 9},
        })

    real_client = genai.Client
    monkeypatch.setenv("GEMINI_API_KEY", "offline-fixture")
    monkeypatch.setattr(genai, "Client", lambda **kwargs: real_client(
        **kwargs, http_options={"base_url": "https://offline.invalid",
                               "async_client_args": {"transport": httpx.MockTransport(respond)}},
    ))
    result = asyncio.run(clients.generate("prompt", provider="google", model="gemini-3.8-flash"))
    usage = result["response_diagnostics"]["usage_metadata"]
    assert usage["reasoning_tokens"] is None
    assert "thoughts_token_count" not in usage


@pytest.mark.parametrize("provider", ["anthropic", "google", "openai"])
@pytest.mark.parametrize("provenance", [False, True])
@pytest.mark.parametrize("raw,valid", [
    ('{"selected_sources":["b","a"]}', True),
    ('{"selected_sources":["a","a"]}', False),
    ('{"selected_sources":["a"]}', False),
    ('{"selected_sources":["a","unknown"]}', False),
    ('{"selected_sources":"a"}', False),
    ('{"selected_sources":["a",4]}', False),
    ('{"other":[]}', False),
    ('{"selected_sources":', False),
    ('Explanation. {"selected_sources":["a","b"]}', False),
])
def test_selector_contract_is_provider_neutral(monkeypatch, provider, provenance, raw, valid):
    from benchmarks.context_selection import application_comparison as app
    candidates = [{"source": "a", "text": "A"}, {"source": "b", "text": "B"}]
    calls = []

    async def generate(prompt, **kwargs):
        calls.append((prompt, kwargs))
        assert kwargs == {"provider": provider, "model": "fixture", "response_schema": SELECTION_SCHEMA}
        assert "Select the 2 sources" in prompt
        assert "Source ID: a" in prompt and "Source ID: b" in prompt
        return {"text": raw, "provider": provider, "model": "fixture",
                "input_tokens": 12, "output_tokens": 9, "latency_seconds": 0.1}

    monkeypatch.setattr(app, "generate", generate)
    if provenance:
        result = asyncio.run(app.select_llm_provenance(
            "question", candidates, [], {}, provider=provider, model="fixture", top_n=2,
        ))
    else:
        result = asyncio.run(app.select_llm(
            "question", candidates, provider=provider, model="fixture", top_n=2,
        ))
    assert len(calls) == 1
    assert result["raw_output"] == raw
    assert (result["parse_error"] is None) == valid
    assert result["selected"] == ([candidates[1], candidates[0]] if valid else [])


@pytest.mark.parametrize("provenance", [False, True])
def test_google_truncation_is_persisted_without_retry(monkeypatch, provenance):
    from benchmarks.context_selection import application_comparison as app
    from benchmarks.context_selection.synthetic.diagnostics import safe_artifact
    requests = []
    raw = '{"selected_sources":["a",'

    def respond(request):
        requests.append(request)
        body = json.loads(request.content)
        assert body["generationConfig"] == {
            "maxOutputTokens": 8192,
            "responseMimeType": "application/json",
            "responseJsonSchema": SELECTION_SCHEMA,
        }
        return httpx.Response(200, json={
            "candidates": [{"content": {"role": "model", "parts": [{"text": raw}]},
                            "finishReason": "MAX_TOKENS"}],
            "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 8},
        })

    real_client = genai.Client
    monkeypatch.setenv("GEMINI_API_KEY", "offline-fixture")
    monkeypatch.setattr(genai, "Client", lambda **kwargs: real_client(
        **kwargs, http_options={"base_url": "https://offline.invalid",
                               "async_client_args": {"transport": httpx.MockTransport(respond)}},
    ))
    candidates = [{"source": "a", "text": "A"}, {"source": "b", "text": "B"}]
    if provenance:
        result = asyncio.run(app.select_llm_provenance_safe(
            "question", candidates, [], {}, provider="google", model="gemini-3.8-flash", top_n=2,
        ))
        assert result["parse_error"] is not None
        selection = result
    else:
        result = asyncio.run(app.select_llm_safe(
            "question", candidates, provider="google", model="gemini-3.8-flash", top_n=2,
        ))["failure"]
        assert result["failure_type"] == "parse_error"
        assert result["answer_score"] == "selection_failure"
        selection = result["selection"]
    assert len(requests) == 1
    saved = safe_artifact(selection)
    assert saved["raw_output"] == raw
    assert saved["response_diagnostics"]["finish_reasons"] == ["MAX_TOKENS"]
