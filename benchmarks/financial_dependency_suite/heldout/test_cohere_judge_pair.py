"""Experiment 2 wiring; all model and evaluator calls are stubbed."""

import asyncio
from copy import deepcopy
import json

import pytest

from benchmarks.financial_dependency_suite import clients
from . import additive_runner as runner, run_benchmark as driver, suite
from .additive_methods import method_by_name


@pytest.fixture
def paired_stubs(monkeypatch):
    calls = {"cohere": [], "judge": [], "omneum": [], "generation": []}
    cases = driver.discover_cases(driver.CASES_DIR)
    by_question = {case.question: case for _, _, case, _ in cases}
    monkeypatch.setattr(driver, "warm_local_models", lambda *args: None)

    def cohere(query, candidates, *, top_n):
        case = by_question[query]
        assert candidates == runner.application_candidates(case)
        assert top_n == min(len(candidates), 2 * case.context_budget)
        calls["cohere"].append(query)
        return {"failure": None, "selection": {"selected": [dict(item, reranker_score=1 - i / 100)
                             for i, item in enumerate(candidates[::-1][:top_n])],
                "model": "rerank-v4.0-pro", "latency_seconds": .2,
                "billed_search_units": 1, "input_tokens": None, "output_tokens": None}}

    async def judge(query, candidates, *, provider, model, top_n):
        assert (provider, model) == ("anthropic", "claude-sonnet-5-5")
        assert top_n == by_question[query].context_budget
        calls["judge"].append((deepcopy(candidates), top_n))
        selection = {"selected": candidates[:top_n], "latency_seconds": .3,
                     "input_tokens": 20, "output_tokens": 5, "parse_error": None,
                     "provider": provider, "model": model}
        # Mutating the judge's input must not affect the treatment or saved shortlist.
        candidates[-1]["reranker_score"] = -999
        return {"failure": None, "selection": selection}

    async def omneum(candidates, observations, source_ids, *, estimator, top_n):
        assert estimator == runner.estimator_config()
        calls["omneum"].append((deepcopy(candidates), top_n))
        return {"selected": candidates[-top_n:], "model": "Omneum",
                "latency_seconds": .1, "cold_integration_latency_seconds": .1,
                "evaluation_latency_seconds": .02}

    async def generate(prompt, model, max_tokens, *, response_schema=None):
        assert model == "claude-sonnet-5-5"
        assert max_tokens == 1024 and response_schema is None
        assert prompt.startswith("Answer the question using only the sources below.\n")
        calls["generation"].append(prompt)
        return {"text": "fixture", "provider": "anthropic", "model": model,
                "latency_seconds": .4, "input_tokens": 11, "output_tokens": 7}

    monkeypatch.setattr(suite, "select_cohere_safe", cohere)
    monkeypatch.setattr(runner.frozen, "select_llm_safe", judge)
    monkeypatch.setattr(runner, "select_omneum", omneum)
    monkeypatch.setattr(clients, "_generate_anthropic", generate)
    return calls


@pytest.mark.parametrize("order", [("cohere_anthropic", "cohere_omneum"),
                                   ("cohere_omneum", "cohere_anthropic")])
def test_24_case_pair_shares_ranked_inputs_and_generation_settings(monkeypatch, tmp_path, paired_stubs, order):
    directory = asyncio.run(driver.run_benchmark(
        results_dir=tmp_path, identifier="paired", trials=1,
        methods=tuple(map(method_by_name, order)),
    ))
    calls = paired_stubs
    assert len(calls["cohere"]) == len(calls["judge"]) == len(calls["omneum"]) == 24
    assert len(calls["generation"]) == 48
    assert calls["judge"] == calls["omneum"]  # IDs, order, text, scores and budgets.
    rows = list(map(json.loads, (directory / "results.jsonl").read_text().splitlines()))
    assert len(rows) == 48
    for control, treatment in zip(rows[::2], rows[1::2]):
        if control["method"] != "cohere_anthropic":
            control, treatment = treatment, control
        c, t = control["selection"], treatment["selection"]
        assert c["cohere_relevance"] == t["cohere_relevance"]
        assert c["cohere_billed_search_units"] == t["cohere_billed_search_units"] == 1
        assert c["cohere_input_tokens"] is None and t["cohere_output_tokens"] is None
        assert t["evaluator_provider"] == "local"
        assert t["evaluator_response_diagnostics"]["model_api_calls"] == 0
        assert c["cohere_shortlist_hash"] == t["cohere_shortlist_hash"]
        assert len(control["selected"]) == len(treatment["selected"]) == c["context_budget"] == t["context_budget"]
        assert c["evaluator_input_tokens"] == 20 and c["evaluator_output_tokens"] == 5
        assert t["evaluator_input_tokens"] == t["evaluator_output_tokens"] == 0
        assert c["evaluator_latency_seconds"] == .3
        assert t["evaluation_latency_seconds"] == .02
        assert c["latency_seconds"] == .5
        assert t["latency_seconds"] == pytest.approx(.3)
        assert control["end_to_end_latency_seconds"] == pytest.approx(.9)
        assert treatment["end_to_end_latency_seconds"] == pytest.approx(.7)
        for row in (control, treatment):
            assert row["generation"]["input_tokens"] == 11
            assert row["generation"]["output_tokens"] == 7
    manifest = json.loads((directory / "manifest.json").read_text())
    assert manifest["selection_pipeline"]["experiment"] == 2
    assert manifest["selection_pipeline"]["generator_max_tokens"] == 1024


def test_resume_uses_saved_shortlist_without_rerank_or_control_judge(monkeypatch, tmp_path, paired_stubs):
    cases = driver.discover_cases(driver.CASES_DIR)[:1]
    monkeypatch.setattr(driver, "discover_cases", lambda _: cases)
    original = suite.run_method

    async def interrupt_treatment(method, *args, **kwargs):
        if method == "cohere_omneum":
            raise RuntimeError("interrupted before treatment")
        return await original(method, *args, **kwargs)

    monkeypatch.setattr(suite, "run_method", interrupt_treatment)
    methods = tuple(map(method_by_name, ("cohere_anthropic", "cohere_omneum")))
    with pytest.raises(RuntimeError, match="interrupted"):
        asyncio.run(driver.run_benchmark(results_dir=tmp_path, identifier="resume-pair",
                                         trials=1, methods=methods))
    monkeypatch.setattr(suite, "run_method", original)
    asyncio.run(driver.run_benchmark(resume=tmp_path / "resume-pair", trials=1, methods=methods))
    assert len(paired_stubs["cohere"]) == len(paired_stubs["judge"]) == len(paired_stubs["omneum"]) == 1
    assert paired_stubs["judge"] == paired_stubs["omneum"]
    assert len(paired_stubs["generation"]) == 2


def test_experiment_rejects_unpaired_route_and_historical_baseline(tmp_path):
    control = method_by_name("cohere_anthropic")
    with pytest.raises(ValueError, match="requires exactly"):
        asyncio.run(driver.run_benchmark(results_dir=tmp_path, methods=(control,)))
    with pytest.raises(ValueError, match="cannot reuse"):
        asyncio.run(driver.run_benchmark(results_dir=tmp_path,
                    methods=(control, method_by_name("cohere_omneum")), baseline_results="unused"))


def test_each_trial_gets_one_fresh_rerank(monkeypatch, tmp_path, paired_stubs):
    cases = driver.discover_cases(driver.CASES_DIR)[:1]
    monkeypatch.setattr(driver, "discover_cases", lambda _: cases)
    asyncio.run(driver.run_benchmark(
        results_dir=tmp_path, identifier="two-trials", trials=2,
        methods=tuple(map(method_by_name, ("cohere_anthropic", "cohere_omneum"))),
    ))
    assert len(paired_stubs["cohere"]) == 2
    assert len(paired_stubs["judge"]) == len(paired_stubs["omneum"]) == 2


def test_shared_rerank_failure_prevents_both_judges_and_generation(monkeypatch, tmp_path, paired_stubs):
    cases = driver.discover_cases(driver.CASES_DIR)[:1]
    monkeypatch.setattr(driver, "discover_cases", lambda _: cases)
    calls = []

    def fail(*args, **kwargs):
        calls.append(True)
        return {"selection": None, "failure": {
            "selected": [], "selection": {"model": "rerank-v4.0-pro", "latency_seconds": None},
            "answer": None, "answer_score": "selection_failure", "generation": None,
            "failure_type": "provider_error", "error": "fixture",
        }}

    monkeypatch.setattr(suite, "select_cohere_safe", fail)
    directory = asyncio.run(driver.run_benchmark(
        results_dir=tmp_path, identifier="failure", trials=1,
        methods=tuple(map(method_by_name, ("cohere_anthropic", "cohere_omneum"))),
    ))
    rows = list(map(json.loads, (directory / "results.jsonl").read_text().splitlines()))
    assert calls == [True]
    assert len(rows) == 2 and all(r["answer_score"] == "selection_failure" for r in rows)
    assert not paired_stubs["judge"] and not paired_stubs["omneum"] and not paired_stubs["generation"]


def test_treatment_cannot_call_claude_judge(monkeypatch, paired_stubs):
    _, _, case, truth = driver.discover_cases(driver.CASES_DIR)[0]
    relevance = suite.select_cohere_safe(
        case.question, runner.application_candidates(case), top_n=2 * case.context_budget,
    )
    monkeypatch.setattr(runner.frozen, "select_llm_safe", lambda *a, **kw: pytest.fail("Claude judge call"))
    result = asyncio.run(runner.run_method(
        "cohere_omneum", case, truth, cohere_relevance=relevance,
        generator_provider="anthropic", generator_model="claude-sonnet-5-5",
    ))
    assert result["selection"]["evaluator_input_tokens"] == 0
    assert len(paired_stubs["generation"]) == 1


def test_rejects_wrong_generator_before_paid_calls(monkeypatch, tmp_path):
    monkeypatch.setattr(driver, "GENERATOR_MODEL", "wrong-model")
    with pytest.raises(ValueError, match="Sonnet 5.5"):
        asyncio.run(driver.run_benchmark(
            results_dir=tmp_path,
            methods=tuple(map(method_by_name, ("cohere_anthropic", "cohere_omneum"))),
        ))


def test_same_selected_context_produces_identical_generation_requests(monkeypatch, tmp_path, paired_stubs):
    cases = driver.discover_cases(driver.CASES_DIR)[:1]
    monkeypatch.setattr(driver, "discover_cases", lambda _: cases)

    async def omneum(candidates, *args, top_n, **kwargs):
        return {"selected": candidates[:top_n], "model": "Omneum",
                "latency_seconds": .1, "evaluation_latency_seconds": .02}

    monkeypatch.setattr(runner, "select_omneum", omneum)
    directory = asyncio.run(driver.run_benchmark(
        results_dir=tmp_path, identifier="same-context", trials=1,
        methods=tuple(map(method_by_name, ("cohere_anthropic", "cohere_omneum"))),
    ))
    rows = list(map(json.loads, (directory / "results.jsonl").read_text().splitlines()))
    assert paired_stubs["generation"][0] == paired_stubs["generation"][1]
    assert rows[0]["generation"]["request_hash"] == rows[1]["generation"]["request_hash"]


def test_reranker_retains_provider_billing_without_changing_ranked_candidates(monkeypatch):
    from types import SimpleNamespace as NS
    from benchmarks.financial_dependency_suite import semantic_reranker as reranker

    candidates = [{"source": "a", "text": "A"}, {"source": "b", "text": "B"}]
    calls = []

    def rerank(**kwargs):
        calls.append(kwargs)
        return NS(results=[NS(index=1, relevance_score=.9), NS(index=0, relevance_score=.5)],
                  meta=NS(billed_units=NS(search_units=1), tokens=None))

    monkeypatch.setenv("COHERE_API_KEY", "fixture-key")
    monkeypatch.setattr(reranker.cohere, "ClientV2", lambda **kw: NS(rerank=rerank))
    result = reranker.rerank_cohere("q", candidates, top_n=2)
    assert calls == [{"model": "rerank-v4.0-pro", "query": "q", "documents": ["A", "B"], "top_n": 2}]
    assert result["selected"] == [{**candidates[1], "reranker_score": .9},
                                  {**candidates[0], "reranker_score": .5}]
    assert result["billed_search_units"] == 1
    assert result["input_tokens"] is None and result["output_tokens"] is None
