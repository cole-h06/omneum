"""Paired Cohere contracts; every provider and evaluator call is replaced."""

import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace as NS

import pytest

from . import additive_runner as runner
from .additive_methods import method_by_name
from .cohere_cache import CohereResponseCache, request_key
from .methods import METHODS
from .test_runner import truth


def test_public_manifest_supports_historical_cache_without_provider():
    from .build_dashboard_summary import BASE
    from .run_benchmark import discover_cases, CASES_DIR
    from .loader import application_candidates

    directory = BASE / "results/20261008T014713Z"
    assert not (directory / "manifest.json").exists()
    discovered = discover_cases(CASES_DIR)
    case = discovered[0][2]
    candidates = application_candidates(case)
    cache = CohereResponseCache(history=[directory], discovered=discovered)
    cache.responses.clear()  # Exercise the manifest/fixture verification fallback.
    result = cache.select(case.question, candidates, depth=1,
                          selector=lambda *args, **kwargs: pytest.fail("provider call"))
    assert result["selection"]["cohere_cache_hit"]
    assert len(result["selection"]["selected"]) == 1


@pytest.mark.parametrize("order", [("cohere", "cohere_omneum"), ("cohere_omneum", "cohere")])
@pytest.mark.parametrize("count,budget", [(7, 2), (3, 2), (1, 1)])
def test_shared_scores_inputs_budget_and_scoring(monkeypatch, tmp_path, order, count, budget):
    candidates = [{"source": f"s{i}", "text": f"text {i}"} for i in range(count)]
    case = NS(question="question", context_budget=budget)
    depth = min(count, 2 * budget)
    ranked = [{**item, "reranker_score": 1 - i / 10}
              for i, item in enumerate(candidates[::-1][:depth])]
    calls = []
    generated = []
    monkeypatch.setattr(runner, "application_candidates", lambda case: candidates)
    observations, source_ids = [object()], {"source": "id"}
    monkeypatch.setattr(runner, "build_observations", lambda case: (observations, source_ids))

    def cohere(query, pool, *, top_n):
        calls.append((query, deepcopy(pool), top_n))
        return {"failure": None, "selection": {
            "selected": deepcopy(ranked), "model": "rerank-v4.0-pro", "latency_seconds": .5,
        }}

    async def omneum(pool, obs, ids, *, estimator, top_n):
        assert pool == ranked
        assert obs is observations and ids is source_ids
        assert top_n == budget
        return {"selected": pool[-budget:], "model": "Omneum", "latency_seconds": .2}

    async def generate(query, documents, **kwargs):
        generated.append(documents)
        return {"failure": None, "generation": {"text": "42", "latency_seconds": .1}}

    monkeypatch.setattr(runner, "select_cohere_safe", cohere)
    monkeypatch.setattr(runner, "select_omneum", omneum)
    monkeypatch.setattr(runner, "generate_answer_safe", generate)
    cache = CohereResponseCache(tmp_path / "cohere_responses.jsonl")
    results = {}
    for method in (*order, *order):
        results[method] = asyncio.run(runner.run_method(
            method, case, truth(), generator_provider="fixture", generator_model="fixture",
            cohere_cache=cache,
        ))
    assert calls == [(case.question, candidates, depth)]
    for method, result in results.items():
        selection = result["selection"]
        assert len(result["selected"]) == budget
        assert selection["relevance_selected"] == ranked
        assert selection["relevance_depth"] == depth
        assert selection["cohere_response_latency_seconds"] == .5
        assert selection["cohere_request_hash"] == request_key(case.question, candidates, depth)
        assert result["selection_score"] == runner.score_selection(result["selected"], truth())
        assert result["answer_score"] == runner.score_answer("42", truth())
    assert results["cohere"]["selection"]["selected"] == ranked[:budget]
    assert results["cohere_omneum"]["selection"]["selected"] == ranked[-budget:]
    assert results["cohere_omneum"]["end_to_end_latency_seconds"] == pytest.approx(.3)
    assert len(generated) == 4
    # A new process/resume reuses the durable response without provider calls.
    restored = CohereResponseCache(tmp_path / "cohere_responses.jsonl")
    result = restored.select(case.question, candidates, depth=depth,
                             selector=lambda *a, **kw: pytest.fail("paid call"))
    assert result["selection"]["selected"] == ranked
    assert result["selection"]["cohere_cache_hit"]


@pytest.mark.parametrize("change", ["query", "text", "order", "source", "depth"])
def test_cache_input_identity(change):
    candidates = [{"source": "a", "text": "A"}, {"source": "b", "text": "B"}]
    query, depth = "question", 2
    original = request_key(query, candidates, depth)
    if change == "query":
        query = "other"
    elif change == "text":
        candidates[0]["text"] = "other"
    elif change == "order":
        candidates.reverse()
    elif change == "source":
        candidates[0]["source"] = "other"
    else:
        depth = 1
    assert request_key(query, candidates, depth) != original


@pytest.mark.parametrize("bad", ["partial", "model", "text", "duplicate", "nan", "order"])
def test_invalid_cache_is_not_reused(tmp_path, bad):
    candidates = [{"source": "a", "text": "A"}, {"source": "b", "text": "B"}]
    good = {"model": "rerank-v4.0-pro", "latency_seconds": .1, "selected": [
        {**candidates[0], "reranker_score": .9}, {**candidates[1], "reranker_score": .8},
    ]}
    invalid = deepcopy(good)
    if bad == "partial":
        invalid["selected"].pop()
    elif bad == "model":
        invalid["model"] = "old"
    elif bad == "text":
        invalid["selected"][0]["text"] = "stale"
    elif bad == "duplicate":
        invalid["selected"][1] = invalid["selected"][0]
    elif bad == "nan":
        invalid["selected"][0]["reranker_score"] = float("nan")
    else:
        invalid["selected"].reverse()
    path = tmp_path / "cohere_responses.jsonl"
    path.write_text(json.dumps({"request_hash": request_key("q", candidates, 2), "selection": invalid}))
    calls = []
    def fresh(*args, **kwargs):
        calls.append(True)
        return {"failure": None, "selection": good}
    result = CohereResponseCache(path).select("q", candidates, depth=2, selector=fresh)
    assert calls == [True]
    assert result["selection"]["selected"] == good["selected"]


def test_failure_prevents_omneum_and_generation(monkeypatch):
    case = NS(question="q", context_budget=1)
    monkeypatch.setattr(runner, "application_candidates", lambda case: [{"source": "a", "text": "A"}])
    failure = {"selected": [], "answer_score": "selection_failure", "failure_type": "provider_error"}
    monkeypatch.setattr(runner, "select_cohere_safe", lambda *a, **kw: {"failure": failure})
    monkeypatch.setattr(runner, "build_observations", lambda *a: pytest.fail("evaluation"))
    monkeypatch.setattr(runner, "generate_answer_safe", lambda *a, **kw: pytest.fail("generation"))
    result = asyncio.run(runner.run_method(
        "cohere_omneum", case, truth(), generator_provider="fixture", generator_model="fixture",
        cohere_cache=CohereResponseCache(),
    ))
    assert result is failure


def test_additive_schedule_and_cli(monkeypatch, tmp_path):
    from . import run_benchmark as driver
    import sys

    discovered = driver.discover_cases(driver.CASES_DIR)
    methods = tuple(map(method_by_name, ("cohere", "cohere_omneum")))
    assert len(discovered) == 24
    assert len(driver.build_schedule(discovered, methods, 10)) == 480
    assert "cohere_omneum" not in {method.name for method in METHODS}
    assert methods[1].model == methods[0].model == "rerank-v4.0-pro"
    async def run(**kwargs):
        assert kwargs["methods"] == methods
        return tmp_path
    monkeypatch.setattr(sys, "argv", ["heldout", "--methods", "cohere", "cohere_omneum"])
    monkeypatch.setattr(driver, "run_benchmark", run)
    driver.main()


@pytest.mark.parametrize("usable", [True, False])
def test_verified_history_reuse(monkeypatch, tmp_path, usable):
    from benchmarks.context_evaluation.reproducibility import sha256_file
    from . import cohere_cache as module

    candidates = [{"source": "a", "text": "A"}, {"source": "b", "text": "B"}]
    case = NS(case_id="fixture", question="q")
    monkeypatch.setattr(module, "application_candidates", lambda case: candidates)
    case_path = tmp_path / "case.json"
    case_path.write_text("frozen input")
    history = tmp_path / "history"
    history.mkdir()
    (history / "manifest.json").write_text(json.dumps({
        "inputs": {str(case_path.resolve()): sha256_file(case_path)},
    }))
    ranked = [{**item, "reranker_score": .9 - i / 10} for i, item in enumerate(candidates)]
    (history / "results.jsonl").write_text(json.dumps({
        "case_id": "fixture", "method": "cohere", "selection": {
            "model": "rerank-v4.0-pro", "latency_seconds": .1,
            "selected": ranked if usable else ranked[:1],
        },
    }))
    before = {p.name: p.read_bytes() for p in history.iterdir()}
    cache = CohereResponseCache(tmp_path / "cohere_responses.jsonl", history=[history],
                                discovered=[(case_path, None, case, None)])
    calls = []
    def fresh(*args, **kwargs):
        calls.append(True)
        return {"failure": None, "selection": {
            "model": "rerank-v4.0-pro", "latency_seconds": .2, "selected": ranked,
        }}
    result = cache.select("q", candidates, depth=2, selector=fresh)
    assert result["selection"]["cohere_cache_hit"] is usable
    assert calls == ([] if usable else [True])
    assert before == {p.name: p.read_bytes() for p in history.iterdir()}


def test_driver_shares_cache_across_routes_and_trials(monkeypatch, tmp_path):
    from . import run_benchmark as driver

    discovered = driver.discover_cases(driver.CASES_DIR)[:1]
    monkeypatch.setattr(driver, "discover_cases", lambda path: discovered)
    monkeypatch.setattr(driver, "warm_local_models", lambda *a: None)
    calls = []
    monkeypatch.setattr(runner, "select_cohere_safe", lambda query, pool, *, top_n: (
        calls.append(top_n) or {"failure": None, "selection": {
            "selected": [{**item, "reranker_score": 1 - i / 100}
                         for i, item in enumerate(pool[:top_n])],
            "model": "rerank-v4.0-pro", "latency_seconds": .1,
        }}
    ))
    async def omneum(pool, *args, top_n, **kwargs):
        return {"selected": pool[-top_n:], "model": "Omneum", "latency_seconds": .2}
    async def generate(*args, **kwargs):
        return {"failure": None, "generation": {"text": "fixture", "latency_seconds": .3}}
    monkeypatch.setattr(runner, "select_omneum", omneum)
    monkeypatch.setattr(runner, "generate_answer_safe", generate)
    directory = asyncio.run(driver.run_benchmark(
        results_dir=tmp_path, trials=2, identifier="paired",
        methods=tuple(map(method_by_name, ("cohere", "cohere_omneum"))),
    ))
    rows = [json.loads(line) for line in (directory / "results.jsonl").read_text().splitlines()]
    assert len(calls) == 1
    assert [(row["method"], row["trial"]) for row in rows] == [
        ("cohere", 1), ("cohere", 2), ("cohere_omneum", 1), ("cohere_omneum", 2),
    ]
    assert len({row["selection"]["cohere_request_hash"] for row in rows}) == 1
    assert (directory / "cohere_responses.jsonl").is_file()
