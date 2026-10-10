"""Google paired wiring; actual Gemini HTTP transport and local evaluation are offline."""

import asyncio
from copy import deepcopy
import json
import re
from types import SimpleNamespace

import httpx
import pytest
from google import genai

from benchmarks.context_evaluation import clients, omneum_rag
from benchmarks.context_evaluation.application_comparison import SELECTION_SCHEMA
from . import additive_runner as runner, run_benchmark as driver, suite
from .additive_methods import method_by_name


@pytest.fixture
def paired_stubs(monkeypatch):
    calls = {"bge": [], "judge": [], "omneum": [], "generation": []}
    cases = driver.discover_cases(driver.CASES_DIR)
    by_question = {case.question: case for _, _, case, _ in cases}
    monkeypatch.setattr(driver, "warm_local_models", lambda *args: None)

    def bge(query, candidates, *, top_n):
        assert top_n == min(len(candidates), 2 * by_question[query].context_budget)
        calls["bge"].append(query)
        return {"selected": [dict(item, reranker_score=1 - i / 100)
                             for i, item in enumerate(candidates[::-1][:top_n])],
                "model": "BAAI/bge-reranker-v2-m3", "latency_seconds": .2}

    original_judge = runner.frozen.select_llm_safe

    async def judge(query, candidates, **kwargs):
        assert kwargs["provider"] == "google"
        assert kwargs["model"] == method_by_name("bge_google").model
        assert kwargs["top_n"] == by_question[query].context_budget
        calls["judge"].append((deepcopy(candidates), kwargs["top_n"]))
        result = await original_judge(query, candidates, **kwargs)
        candidates[-1]["reranker_score"] = -999  # Isolation across arms and resume.
        return result

    def google_response(request):
        body = json.loads(request.content)
        prompt = body["contents"][0]["parts"][0]["text"]
        assert method_by_name("bge_google").model in request.url.path
        assert body["generationConfig"] == {
            "maxOutputTokens": 8192,
            "responseMimeType": "application/json",
            "responseJsonSchema": SELECTION_SCHEMA,
        }  # Retain default thinking; do not disable it to reduce cost/latency.
        candidates, budget = calls["judge"][-1]
        ids = [item["source"] for item in candidates]
        assert re.findall(r"Source ID: ([^\n]+)", prompt) == ids
        assert all(item["text"] in prompt for item in candidates)
        case = next(case for question, case in by_question.items() if question in prompt)
        assert all(f"Source ID: {item.source_id}\n" not in prompt
                   for item in case.candidates if item.source_id not in ids)
        return httpx.Response(200, json={
            "candidates": [{"content": {"role": "model", "parts": [{
                "text": json.dumps({"selected_sources": ids[:budget]}),
            }]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 5,
                              "thoughtsTokenCount": 7, "totalTokenCount": 32},
        })

    real_google_client = genai.Client
    monkeypatch.setenv("GEMINI_API_KEY", "offline-fixture")
    monkeypatch.setattr(clients.genai, "Client", lambda **kwargs: real_google_client(
        **kwargs, http_options={"base_url": "https://offline.invalid",
                               "async_client_args": {"transport": httpx.MockTransport(google_response)}},
    ))

    original_omneum = runner.select_omneum

    async def omneum(candidates, observations, source_ids, **kwargs):
        calls["omneum"].append((deepcopy(candidates), kwargs["top_n"]))
        # Exercise actual mapping and structural selection, stubbing only SDK evaluation.
        return await original_omneum(candidates, observations, source_ids, **kwargs)

    async def evaluate(mapped, *, estimator):
        return SimpleNamespace(claim_support=[], source_reliability=[],
                               pairwise_dependencies=[], dependency_cluster_threshold=.5,
                               evaluation_latency_ms=20)

    async def generate(prompt, model, max_tokens, *, response_schema=None):
        assert model == "claude-sonnet-5-5" and max_tokens == 1024
        assert response_schema is None
        calls["generation"].append(prompt)
        return {"text": "fixture", "provider": "anthropic", "model": model,
                "latency_seconds": .4, "input_tokens": 11, "output_tokens": 7}

    monkeypatch.setattr(runner.frozen, "select_bge", bge)
    monkeypatch.setattr(runner.frozen, "select_llm_safe", judge)
    monkeypatch.setattr(runner, "select_omneum", omneum)
    monkeypatch.setattr(omneum_rag, "evaluate_context", evaluate)
    monkeypatch.setattr(clients, "_generate_anthropic", generate)
    return calls


@pytest.mark.parametrize("order", [("bge_google", "bge_omneum"), ("bge_omneum", "bge_google")])
def test_pair_shares_bge_pool_budget_and_generation(monkeypatch, tmp_path, paired_stubs, order):
    directory = asyncio.run(driver.run_benchmark(
        results_dir=tmp_path, identifier="google-pair", trials=10,
        methods=tuple(map(method_by_name, order)),
    ))
    calls = paired_stubs
    assert len(calls["bge"]) == len(calls["judge"]) == len(calls["omneum"]) == 240
    assert len(calls["generation"]) == 480
    assert calls["judge"] == calls["omneum"]  # IDs, order, scores, text, budget.
    rows = list(map(json.loads, (directory / "results.jsonl").read_text().splitlines()))
    pairs = {}
    for row in rows:
        pairs.setdefault((row["case_id"], row["trial"]), {})[row["method"]] = row
    for pair in pairs.values():
        control, treatment = pair["bge_google"], pair["bge_omneum"]
        c, t = control["selection"], treatment["selection"]
        assert c["bge_relevance"] == t["bge_relevance"]
        assert c["bge_shortlist_hash"] == t["bge_shortlist_hash"]
        assert len(control["selected"]) == len(treatment["selected"]) == c["context_budget"] == t["context_budget"]
        assert c["evaluator_provider"] == "google"
        assert c["evaluator_input_tokens"] == 20
        assert t["evaluator_input_tokens"] == t["evaluator_output_tokens"] == 0
        assert t["evaluator_response_diagnostics"]["model_api_calls"] == 0
        # With identical selections, actual generation requests must be identical.
        assert control["generation"]["request_hash"] == treatment["generation"]["request_hash"]
        assert c["latency_seconds"] == .2 + c["evaluator_latency_seconds"]
        assert c["response_diagnostics"]["usage_metadata"]["reasoning_tokens"] == 7
        assert t["evaluation_latency_seconds"] == .02
    manifest = json.loads((directory / "manifest.json").read_text())
    assert manifest["selection_pipeline"]["experiment"] == 4
    assert manifest["selection_pipeline"]["control"] == "bge_google"
    assert manifest["selection_pipeline"]["generator_max_tokens"] == 1024
    assert manifest["selection_pipeline"]["judge_model"] == "gemini-3.8-flash"
    assert manifest["selection_pipeline"]["judge_max_output_tokens"] == 8192
    assert manifest["selection_pipeline"]["judge_thinking_policy"] == "provider default; no override"
    assert manifest["checkpoint_contract"]["selection_pipeline"] == manifest["selection_pipeline"]
    assert len(rows) == 480
    assert len({(row["case_id"], row["method"], row["trial"]) for row in rows}) == 480


@pytest.mark.parametrize("order", [("bge_google", "bge_omneum"), ("bge_omneum", "bge_google")])
def test_resume_uses_saved_bge_pool(monkeypatch, tmp_path, paired_stubs, order):
    cases = driver.discover_cases(driver.CASES_DIR)[:1]
    monkeypatch.setattr(driver, "discover_cases", lambda _: cases)
    original = suite.run_method

    async def interrupt(method, *args, **kwargs):
        if method == order[1]:
            raise RuntimeError("interrupted")
        return await original(method, *args, **kwargs)

    methods = tuple(map(method_by_name, order))
    monkeypatch.setattr(suite, "run_method", interrupt)
    with pytest.raises(RuntimeError, match="interrupted"):
        asyncio.run(driver.run_benchmark(results_dir=tmp_path, identifier="resume", trials=1, methods=methods))
    monkeypatch.setattr(suite, "run_method", original)
    asyncio.run(driver.run_benchmark(resume=tmp_path / "resume", trials=1, methods=methods))
    assert len(paired_stubs["bge"]) == len(paired_stubs["judge"]) == len(paired_stubs["omneum"]) == 1
    assert paired_stubs["judge"] == paired_stubs["omneum"]


def test_pair_rejects_confounded_settings(monkeypatch, tmp_path):
    methods = tuple(map(method_by_name, ("bge_google", "bge_omneum")))
    with pytest.raises(ValueError, match="requires exactly"):
        asyncio.run(driver.run_benchmark(results_dir=tmp_path, methods=methods[:1]))
    with pytest.raises(ValueError, match="cannot reuse"):
        asyncio.run(driver.run_benchmark(results_dir=tmp_path, methods=methods, baseline_results="unused"))
    with pytest.raises(ValueError, match="requires exactly"):
        asyncio.run(driver.run_benchmark(results_dir=tmp_path, methods=methods + (method_by_name("bge_openai"),)))
    monkeypatch.setattr(driver, "GENERATOR_PROVIDER", "google")
    with pytest.raises(ValueError, match="Sonnet 5.5"):
        asyncio.run(driver.run_benchmark(results_dir=tmp_path, methods=methods))
    monkeypatch.setattr(driver, "GENERATOR_PROVIDER", "anthropic")
    monkeypatch.setattr(driver, "GENERATOR_MODEL", "other")
    with pytest.raises(ValueError, match="Sonnet 5.5"):
        asyncio.run(driver.run_benchmark(results_dir=tmp_path, methods=methods))


def test_google_selection_requires_shared_pool():
    case = driver.discover_cases(driver.CASES_DIR)[0][2]
    with pytest.raises(ValueError, match="paired shared shortlist"):
        asyncio.run(runner.run_selection("bge_google", case))
