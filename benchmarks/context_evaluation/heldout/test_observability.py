import asyncio
import json

import httpx
import pytest
from anthropic import AsyncAnthropic
from google import genai

from benchmarks.context_evaluation import clients
from . import runner, suite
from .artifacts import checkpoint
from .methods import MethodSpec
from .run_benchmark import CASES_DIR, discover_cases


def execute(tmp_path, monkeypatch, provider, method):
    async def answer(*args, **kwargs):
        return {"generation": {"text": "612", "latency_seconds": 0.1}, "failure": None}

    monkeypatch.setattr(runner, "generate_answer_safe", answer)
    _, _, case, truth = discover_cases(CASES_DIR)[0]
    records = []

    def persist(record):
        records.append(record)
        checkpoint(tmp_path / "results.jsonl", records)

    asyncio.run(suite.run_case(
        case, truth, trials=1, generator_provider="anthropic", generator_model="generator",
        methods=(MethodSpec(name=provider + ("_provenance" if method == "llm_provenance" else ""),
                            method=method, provider=provider, model="fixture-model"),),
        on_result=persist,
    ))
    return json.loads((tmp_path / "results.jsonl").read_text())


@pytest.mark.parametrize("method", ["llm", "llm_provenance"])
@pytest.mark.parametrize("kind", ["valid", "empty", "thinking", "prose", "truncated"])
def test_anthropic_diagnostics_to_disk(tmp_path, monkeypatch, kind, method):
    case = discover_cases(CASES_DIR)[0][2]
    valid = json.dumps({"selected_sources": [c.source_id for c in case.candidates[:case.context_budget]]})
    content = {
        "valid": [{"type": "text", "text": valid}],
        "empty": [],
        "thinking": [{"type": "thinking", "thinking": "private reasoning", "signature": "private-signature"}],
        "prose": [{"type": "text", "text": "I recommend these sources."}],
        "truncated": [{"type": "text", "text": '{"selected_sources": ['}],
    }[kind]
    stop = "max_tokens" if kind == "truncated" else "end_turn"

    def respond(request):
        return httpx.Response(200, headers={"x-private": "private-header"}, json={
            "id": "msg_fixture", "type": "message", "role": "assistant", "model": "fixture-model",
            "content": content, "stop_reason": stop, "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 1024 if kind == "truncated" else 5},
        })

    monkeypatch.setenv("ANTHROPIC_API_KEY", "private-api-key")
    monkeypatch.setattr(clients, "AsyncAnthropic", lambda: AsyncAnthropic(
        api_key="private-api-key", base_url="https://offline.invalid",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    ))
    record = execute(tmp_path, monkeypatch, "anthropic", method)
    if kind == "valid":
        assert record["answer_score"] == "correct"
        assert record["selection"]["raw_output"] == valid
        metadata = record["selection"]["response_diagnostics"]
    else:
        assert record["answer_score"] == "selection_failure"
        assert record["failure_type"] == "parse_error"
        metadata = record["diagnostics"]
        assert "raw_output" not in metadata
        assert record["selection"]["raw_output"] == "".join(b["text"] for b in content if b["type"] == "text")
        for key in ("case_id", "method", "trial", "failure_type"):
            assert metadata[key] == record[key]
        assert metadata["provider"] == "anthropic"
        assert metadata["model"] == "fixture-model"
    assert metadata["stop_reason"] == stop
    assert metadata["content_block_types"] == [b["type"] for b in content]
    serialized = (tmp_path / "results.jsonl").read_text()
    for secret in ("private-api-key", "private-header", "private reasoning", "private-signature"):
        assert secret not in serialized


@pytest.mark.parametrize("method", ["llm", "llm_provenance"])
@pytest.mark.parametrize("status", [429, 503])
def test_google_failure_diagnostics_to_disk(tmp_path, monkeypatch, status, method):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, json={"error": {
            "code": status, "message": "authorization: unknown-private-credential",
            "status": "RESOURCE_EXHAUSTED" if status == 429 else "UNAVAILABLE",
        }})

    real_client = genai.Client
    monkeypatch.setenv("GEMINI_API_KEY", "private-google-key")
    monkeypatch.setattr(clients.genai, "Client", lambda **kwargs: real_client(
        **kwargs, http_options={"base_url": "https://offline.invalid",
                                "async_client_args": {"transport": httpx.MockTransport(respond)}},
    ))
    record = execute(tmp_path, monkeypatch, "google", method)
    assert len(requests) == 1
    assert record["answer_score"] == "selection_failure"
    diagnostic = record["diagnostics"]
    assert diagnostic["failure_type"] == "provider_error"
    assert diagnostic["http_status"] == status
    assert diagnostic["error_type"] == ("ClientError" if status == 429 else "ServerError")
    assert "raw_output" not in diagnostic
    assert diagnostic["provider"] == "google"
    assert diagnostic["model"] == "fixture-model"
    serialized = (tmp_path / "results.jsonl").read_text()
    assert "unknown-private-credential" not in serialized
    assert "private-google-key" not in serialized


def test_artifact_boundary_redacts_credentials_and_drops_headers(tmp_path, monkeypatch):
    monkeypatch.setenv("CUSTOM_API_KEY", "environment-credential")
    record = {
        "answer_score": "selection_failure", "failure_type": "parse_error",
        "selection": {"raw_output": "environment-credential sk-fake-secret authorization: Bearer bearer-secret"},
        "headers": {"Authorization": "header-secret"},
        "request_headers": {"X-Api-Key": "header-secret"},
        "environment": {"OTHER": "env-secret"},
        "response_diagnostics": {"stop_reason": "end_turn", "secret_extra": "extra-secret"},
    }
    checkpoint(tmp_path / "results.jsonl", [record])
    text = (tmp_path / "results.jsonl").read_text()
    for secret in ("environment-credential", "sk-fake-secret", "bearer-secret", "header-secret", "env-secret", "extra-secret"):
        assert secret not in text
    assert json.loads(text)["failure_type"] == "parse_error"


def test_google_finish_reason_is_preserved(tmp_path, monkeypatch):
    def respond(request):
        return httpx.Response(200, json={
            "candidates": [{"content": {"role": "model", "parts": [{"text": "{"}]},
                            "finishReason": "MAX_TOKENS"}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 1024},
        })

    real_client = genai.Client
    monkeypatch.setenv("GEMINI_API_KEY", "private-google-key")
    monkeypatch.setattr(clients.genai, "Client", lambda **kwargs: real_client(
        **kwargs, http_options={"base_url": "https://offline.invalid",
                                "async_client_args": {"transport": httpx.MockTransport(respond)}},
    ))
    record = execute(tmp_path, monkeypatch, "google", "llm")
    assert record["answer_score"] == "selection_failure"
    assert record["diagnostics"]["finish_reasons"] == ["MAX_TOKENS"]
    assert "raw_output" not in record["diagnostics"]
    assert record["selection"]["raw_output"] == "{"


def test_provider_usage_metadata_is_saved_with_unavailable_fields_null(tmp_path):
    usage = {
        "prompt_token_count": 17,
        "candidates_token_count": 6,
        "thoughts_token_count": 11,
        "total_token_count": 34,
        "reasoning_tokens": 11,
        "cache_tokens_details": {"text_tokens": 2},
    }
    checkpoint(tmp_path / "usage.jsonl", [{
        "response_diagnostics": {"usage_metadata": usage},
    }])
    saved = json.loads((tmp_path / "usage.jsonl").read_text())
    assert saved["response_diagnostics"]["usage_metadata"] == usage

    missing = dict(usage, reasoning_tokens=None)
    checkpoint(tmp_path / "missing-usage.jsonl", [{
        "response_diagnostics": {"usage_metadata": missing},
    }])
    saved_missing = json.loads((tmp_path / "missing-usage.jsonl").read_text())
    assert saved_missing["response_diagnostics"]["usage_metadata"]["reasoning_tokens"] is None


def test_token_efficiency_summary_survives_checkpoint_sanitization(tmp_path):
    summary = {
        "fixture": {
            "generator_usage": {
                "input_tokens": {"n": 1, "sum": 10},
                "output_tokens": {"n": 1, "sum": 5},
                "total_tokens": {"n": 1, "sum": 15},
                "token_efficiency": {
                    "definition": "correct answers / observed tokens",
                    "correct_answers": 1,
                    "usage_covered_records": 1,
                    "correct_per_1000_tokens": 1000 / 15,
                },
            },
        },
    }
    checkpoint(tmp_path / "summary.jsonl", [summary])
    saved = json.loads((tmp_path / "summary.jsonl").read_text())
    assert saved["fixture"]["generator_usage"]["token_efficiency"] == summary["fixture"]["generator_usage"]["token_efficiency"]


def test_provider_error_body_keeps_typed_fields_and_omits_message(monkeypatch):
    from .diagnostics import safe_artifact

    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-secret-key")
    body = {
        "type": "error",
        "error": {
            "type": "invalid_request_error",
            "code": "invalid_parameter",
            "message": "Invalid request schema; account 612 production ID. Authorization: Bearer fixture-secret-key",
        },
        "request_id": "request-fixture-id",
    }
    # Match the representation emitted by the installed Anthropic SDK.
    error_text = f"Error code: 400 - {body!r}"
    record = safe_artifact({
        "case_id": "analytics_derived_metric_cycle",
        "method": "vector",
        "answer_score": "generation_failure",
        "failure_type": "provider_error",
        "error": error_text,
        "response_diagnostics": {"http_status": 400, "error_type": "BadRequestError"},
    })
    details = record["response_diagnostics"]["provider_error_details"]
    assert details["type"] == "invalid_request_error"
    assert details["code"] == "invalid_parameter"
    assert "message" not in details
    assert "fixture-secret-key" not in json.dumps(record)
    assert "request-fixture-id" not in json.dumps(record)
    assert "612" not in json.dumps(record)
    assert "production" not in json.dumps(record)


def test_safe_artifact_accepts_raw_runner_result_without_case_id(monkeypatch):
    from .diagnostics import safe_artifact

    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-secret-key")
    # run_method returns this result shape before suite.py adds case/method/trial context.
    result = {
        "selected": [],
        "answer": None,
        "answer_score": "selection_failure",
        "failure_type": "provider_error",
        "error": ('Error code: 400 - {"type":"error","error":{"type":"invalid_request_error",'
                  '"code":"invalid_parameter","message":"safe fixture message"}}'),
        "selection": {"provider": "anthropic", "model": "fixture"},
        "generation": None,
    }

    saved = safe_artifact(result)

    assert saved["failure_type"] == "provider_error"
    assert saved["error"] == "Provider request failed; see diagnostic type and status."
    details = saved["diagnostics"]["provider_error_details"]
    assert details["type"] == "invalid_request_error"
    assert details["code"] == "invalid_parameter"
    # Provider messages can echo application data, even with case context.
    assert "message" not in details
