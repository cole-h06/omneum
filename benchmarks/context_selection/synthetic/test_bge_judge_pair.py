"""Experiment 1 wiring; all model and evaluator calls are stubbed."""

import asyncio
from copy import deepcopy
import json

import pytest

from benchmarks.context_selection import clients
from . import additive_runner as runner, run_benchmark as driver, suite
from .additive_methods import method_by_name


@pytest.fixture
def paired_stubs(monkeypatch):
    calls = {"bge": [], "judge": [], "omneum": [], "generation": []}
    cases = driver.discover_cases(driver.CASES_DIR)
    by_question = {case.question: case for _, _, case, _ in cases}
    monkeypatch.setattr(driver, "warm_local_models", lambda *args: None)

    def bge(query, candidates, *, top_n):
        case = by_question[query]
        assert candidates == runner.application_candidates(case)
        assert top_n == min(len(candidates), 2 * case.context_budget)
        calls["bge"].append(query)
        return {"selected": [dict(item, reranker_score=1 - i / 100)
                             for i, item in enumerate(candidates[::-1][:top_n])],
                "model": "BAAI/bge-reranker-v2-m3", "latency_seconds": .2}

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

    monkeypatch.setattr(runner.frozen, "select_bge", bge)
    monkeypatch.setattr(runner.frozen, "select_llm_safe", judge)
    monkeypatch.setattr(runner, "select_omneum", omneum)
    monkeypatch.setattr(clients, "_generate_anthropic", generate)
    return calls


@pytest.mark.parametrize("order", [("bge_anthropic", "bge_omneum"),
                                   ("bge_omneum", "bge_anthropic")])
def test_paired_inputs(monkeypatch, tmp_path, paired_stubs, order):
    directory = asyncio.run(driver.run_benchmark(
        results_dir=tmp_path, identifier="paired", trials=1,
        methods=tuple(map(method_by_name, order)),
    ))
    calls = paired_stubs
    assert len(calls["bge"]) == len(calls["judge"]) == len(calls["omneum"]) == 24
    assert len(calls["generation"]) == 48
    assert calls["judge"] == calls["omneum"]  # IDs, order, text, scores and budgets.
    rows = list(map(json.loads, (directory / "results.jsonl").read_text().splitlines()))
    assert len(rows) == 48
    for control, treatment in zip(rows[::2], rows[1::2]):
        if control["method"] != "bge_anthropic":
            control, treatment = treatment, control
        c, t = control["selection"], treatment["selection"]
        assert c["bge_relevance"] == t["bge_relevance"]
        assert c["bge_shortlist_hash"] == t["bge_shortlist_hash"]
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
    assert manifest["selection_pipeline"]["experiment"] == 1
    assert manifest["selection_pipeline"]["generator_max_tokens"] == 1024


def test_resume_shortlist(monkeypatch, tmp_path, paired_stubs):
    cases = driver.discover_cases(driver.CASES_DIR)[:1]
    monkeypatch.setattr(driver, "discover_cases", lambda _: cases)
    original = suite.run_method

    async def interrupt_treatment(method, *args, **kwargs):
        if method == "bge_omneum":
            raise RuntimeError("interrupted before treatment")
        return await original(method, *args, **kwargs)

    monkeypatch.setattr(suite, "run_method", interrupt_treatment)
    methods = tuple(map(method_by_name, ("bge_anthropic", "bge_omneum")))
    with pytest.raises(RuntimeError, match="interrupted"):
        asyncio.run(driver.run_benchmark(results_dir=tmp_path, identifier="resume-pair",
                                         trials=1, methods=methods))
    monkeypatch.setattr(suite, "run_method", original)
    asyncio.run(driver.run_benchmark(resume=tmp_path / "resume-pair", trials=1, methods=methods))
    assert len(paired_stubs["bge"]) == len(paired_stubs["judge"]) == len(paired_stubs["omneum"]) == 1
    assert paired_stubs["judge"] == paired_stubs["omneum"]
    assert len(paired_stubs["generation"]) == 2


def test_invalid_pairing(tmp_path):
    control = method_by_name("bge_anthropic")
    with pytest.raises(ValueError, match="requires exactly"):
        asyncio.run(driver.run_benchmark(results_dir=tmp_path, methods=(control,)))
    with pytest.raises(ValueError, match="cannot reuse"):
        asyncio.run(driver.run_benchmark(results_dir=tmp_path,
                    methods=(control, method_by_name("bge_omneum")), baseline_results="unused"))
