"""Claude + Omneum contracts; all provider and evaluator calls are stubbed."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from benchmarks.financial_dependency_suite.heldout import additive_runner as runner
from benchmarks.financial_dependency_suite.heldout.additive_methods import method_by_name
from benchmarks.financial_dependency_suite.heldout.baseline_reuse import load_anthropic_baseline
from benchmarks.financial_dependency_suite.heldout.run_benchmark import discover_cases
from benchmarks.financial_dependency_suite.heldout.test_runner import truth
from benchmarks.financial_dependency_suite.heldout.loader import load_case


BASELINE = Path(__file__).parent / "results/clean-validation-1trial-20261004T013826Z/results.jsonl"


@pytest.mark.parametrize("count,budget,depth", [(10, 3, 6), (3, 2, 3), (1, 1, 1)])
def test_claude_shortlist_omneum_final_budget_and_scoring(monkeypatch, count, budget, depth):
    candidates = [{"source": f"s{i}", "text": f"candidate {i}"} for i in range(count)]
    case = NS(question="question", context_budget=budget)
    shortlist = candidates[::-1][:depth]
    final = shortlist[:budget]
    truth_data = truth()
    calls, generated, evaluated = [], [], []
    observations, source_ids = [object()], {item["source"]: item["source"] for item in candidates}

    monkeypatch.setattr(runner, "application_candidates", lambda _: candidates)
    monkeypatch.setattr(runner, "build_observations", lambda _: (observations, source_ids))

    async def claude(query, pool, *, provider, model, top_n):
        # Ground truth is intentionally absent from the evaluator call contract.
        calls.append((query, pool, provider, model, top_n))
        return {"failure": None, "selection": {
            "selected": shortlist, "provider": provider, "model": model,
            "latency_seconds": .2, "input_tokens": 30, "output_tokens": 8,
            "raw_output": json.dumps({"selected_sources": [x["source"] for x in shortlist]}),
            "response_diagnostics": {"stop_reason": "end_turn"},
        }}

    async def omneum(pool, obs, ids, *, estimator, top_n):
        evaluated.append((pool, obs, ids, top_n))
        return {"selected": final, "model": "Omneum", "latency_seconds": .4,
                "cold_integration_latency_seconds": .4,
                "evaluation_latency_seconds": .1, "evaluation": {"fixture": True}}

    async def generate(query, documents, *, provider, model):
        generated.append((query, documents, provider, model))
        return {"failure": None, "generation": {
            "text": "answer 42", "provider": provider, "model": model,
            "latency_seconds": .5, "input_tokens": 11, "output_tokens": 4,
        }}

    monkeypatch.setattr(runner, "select_llm_safe", claude)
    monkeypatch.setattr(runner, "select_omneum", omneum)
    monkeypatch.setattr(runner, "generate_answer_safe", generate)
    result = asyncio.run(runner.run_method(
        "anthropic_omneum", case, truth_data, provider="anthropic",
        model="claude-sonnet-5-5", generator_provider="anthropic",
        generator_model="claude-sonnet-5-5",
    ))

    assert calls == [("question", candidates, "anthropic", "claude-sonnet-5-5", depth)]
    assert evaluated == [(shortlist, observations, source_ids, budget)]
    assert result["selected"] == [item["source"] for item in final]
    assert generated == [("question", final, "anthropic", "claude-sonnet-5-5")]
    assert len(final) == budget
    assert result["selection_score"] == runner.score_selection(result["selected"], truth_data)
    assert result["answer_score"] == runner.score_answer("answer 42", truth_data)
    assert result["selection"]["relevance_depth"] == depth
    assert result["selection"]["evaluator_input_tokens"] == 30
    assert result["selection"]["evaluator_output_tokens"] == 8
    assert result["selection"]["request_hash"]
    assert result["generation"]["request_hash"]
    assert result["selection"]["latency_seconds"] == pytest.approx(.6)
    assert result["end_to_end_latency_seconds"] == pytest.approx(1.1)
    assert result["inference_cost"] == {"usd": None, "availability": "no_pricing_defined"}


def test_existing_baseline_is_compatible_and_rows_are_preserved():
    discovered = discover_cases(Path(__file__).with_name("cases"))
    reused, metadata = load_anthropic_baseline(
        BASELINE, discovered, generator_model="claude-sonnet-5-5",
    )
    original = [json.loads(line) for line in BASELINE.read_text().splitlines()
                if json.loads(line).get("method") == "anthropic"]
    assert len(reused) == len(original) == 24
    assert metadata["compatibility"]["case_and_ground_truth_hashes"] == "verified"
    for row in original:
        assert reused[(row["case_id"], "anthropic", 1)] == row


def test_loader_retains_adversarial_category_metadata(tmp_path):
    source = Path(__file__).parent / "cases/analytics_derived_metric_cycle/case.json"
    payload = json.loads(source.read_text())
    payload["category"] = "lineage"
    payload["adversarial_category"] = "stale_dependency"
    path = tmp_path / "case.json"
    path.write_text(json.dumps(payload))
    case = load_case(path)
    assert case.category == "lineage"
    assert case.adversarial_category == "stale_dependency"


def test_omneum_underfill_is_a_selection_failure_without_generation(monkeypatch):
    candidates = [{"source": f"s{i}", "text": str(i)} for i in range(4)]
    case = NS(question="question", context_budget=2)
    monkeypatch.setattr(runner, "application_candidates", lambda _: candidates)
    monkeypatch.setattr(runner, "build_observations", lambda _: ([], {}))
    async def claude(*args, top_n, **kwargs):
        return {"failure": None, "selection": {
            "selected": candidates[:top_n], "provider": "anthropic",
            "model": "claude-sonnet-5-5", "latency_seconds": .1,
            "input_tokens": 4, "output_tokens": 2, "raw_output": "{}",
        }}
    async def underfilled(*args, **kwargs):
        return {"selected": candidates[:1], "model": "Omneum", "latency_seconds": .2}
    async def no_generation(*args, **kwargs):
        pytest.fail("must not answer from fewer than the final context budget")
    monkeypatch.setattr(runner, "select_llm_safe", claude)
    monkeypatch.setattr(runner, "select_omneum", underfilled)
    monkeypatch.setattr(runner, "generate_answer_safe", no_generation)
    result = asyncio.run(runner.run_method(
        "anthropic_omneum", case, truth(), generator_provider="anthropic",
        generator_model="claude-sonnet-5-5",
    ))
    assert result["answer_score"] == "selection_failure"
    assert result["failure_type"] == "omneum_selection_contract"
    assert result["selection"]["request_hash"]


def test_generation_failure_keeps_selection_score_and_request_identity(monkeypatch):
    candidates = [{"source": f"s{i}", "text": str(i)} for i in range(4)]
    case = NS(question="question", context_budget=2)
    monkeypatch.setattr(runner, "application_candidates", lambda _: candidates)
    monkeypatch.setattr(runner, "build_observations", lambda _: ([], {}))
    async def claude(*args, top_n, **kwargs):
        return {"failure": None, "selection": {
            "selected": candidates[:top_n], "provider": "anthropic",
            "model": "claude-sonnet-5-5", "latency_seconds": .1,
            "input_tokens": 4, "output_tokens": 2, "raw_output": "{}",
        }}
    async def omneum(*args, top_n, **kwargs):
        return {"selected": candidates[:top_n], "model": "Omneum", "latency_seconds": .2}
    async def failed_generation(*args, **kwargs):
        return {"failure": {"answer": None, "answer_score": "generation_failure",
                            "failure_type": "provider_error", "generation": None}}
    monkeypatch.setattr(runner, "select_llm_safe", claude)
    monkeypatch.setattr(runner, "select_omneum", omneum)
    monkeypatch.setattr(runner, "generate_answer_safe", failed_generation)
    result = asyncio.run(runner.run_method(
        "anthropic_omneum", case, truth(), generator_provider="anthropic",
        generator_model="claude-sonnet-5-5",
    ))
    assert result["answer_score"] == "generation_failure"
    assert result["selection_score"] == runner.score_selection(
        [item["source"] for item in candidates[:2]], truth(),
    )
    assert result["generation_request_hash"]


@pytest.mark.parametrize("mismatch", ["truth_hash", "model", "budget"])
def test_baseline_mismatch_is_rejected(tmp_path, mismatch):
    import hashlib
    import shutil

    source_dir = BASELINE.parent
    copied = tmp_path / "baseline"
    shutil.copytree(source_dir, copied)
    manifest_path = copied / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if mismatch == "truth_hash":
        key = next(key for key in manifest["inputs"] if key.endswith("ground_truth.json"))
        manifest["inputs"][key] = "0" * 64
    elif mismatch == "model":
        manifest["models"]["generator"] = "different-model"
    else:
        rows = [json.loads(line) for line in (copied / "results.jsonl").read_text().splitlines()]
        row = next(row for row in rows if row["method"] == "anthropic")
        row["selected"] = row["selected"][:-1]
        (copied / "results.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        load_anthropic_baseline(copied / "results.jsonl", discover_cases(Path(__file__).with_name("cases")),
                                generator_model="claude-sonnet-5-5")


def test_baseline_import_and_paired_schedule_never_regenerate_claude_rows(monkeypatch, tmp_path):
    from benchmarks.financial_dependency_suite.heldout import run_benchmark as driver

    discovered = driver.discover_cases(driver.CASES_DIR)
    methods = (method_by_name("anthropic"), method_by_name("anthropic_omneum"))
    calls = {"evaluator": 0, "generator": 0, "omneum": 0}

    async def evaluator(query, candidates, *, provider, model, top_n):
        calls["evaluator"] += 1
        return {"failure": None, "selection": {
            "selected": candidates[:top_n], "provider": provider, "model": model,
            "latency_seconds": .01, "input_tokens": 12, "output_tokens": 5,
            "raw_output": json.dumps({"selected_sources": [x["source"] for x in candidates[:top_n]]}),
        }}

    async def omneum(pool, observations, source_ids, *, estimator, top_n):
        calls["omneum"] += 1
        return {"selected": pool[:top_n], "model": "Omneum", "latency_seconds": .02,
                "cold_integration_latency_seconds": .02, "evaluation_latency_seconds": .005}

    async def generator(query, documents, *, provider, model):
        calls["generator"] += 1
        return {"failure": None, "generation": {
            "text": "42", "provider": provider, "model": model,
            "latency_seconds": .03, "input_tokens": 10, "output_tokens": 2,
        }}

    monkeypatch.setattr(driver, "warm_local_models", lambda *args: pytest.fail("unexpected local model warmup"))
    monkeypatch.setattr(runner, "select_llm_safe", evaluator)
    monkeypatch.setattr(runner, "select_omneum", omneum)
    monkeypatch.setattr(runner, "generate_answer_safe", generator)
    directory = asyncio.run(driver.run_benchmark(
        results_dir=tmp_path, trials=1, identifier="claude-paired",
        methods=methods, baseline_results=BASELINE,
    ))
    rows = [json.loads(line) for line in (directory / "results.jsonl").read_text().splitlines()]
    original = {row["case_id"]: row for row in
                (json.loads(line) for line in BASELINE.read_text().splitlines())
                if row.get("method") == "anthropic"}
    assert len(rows) == 48
    assert calls == {"evaluator": 24, "generator": 24, "omneum": 24}
    assert all(row == original[row["case_id"]] for row in rows if row["method"] == "anthropic")
    assert all(row["method"] in {"anthropic", "anthropic_omneum"} for row in rows)
    output_manifest = json.loads((directory / "manifest.json").read_text())
    assert output_manifest["baseline_reuse"]["reused_records"] == 24
    assert output_manifest["selection_pipeline"]["anthropic_omneum"]["shortlist_depth"].startswith("min(")
    paired = next(row for row in rows if row["method"] == "anthropic_omneum")
    assert paired["selection"]["evaluator_input_tokens"] == 12
    assert paired["selection"]["evaluator_output_tokens"] == 5
    assert paired["selection"]["evaluator_raw_output"]
    assert paired["selection"]["request_hash"]
    assert paired["generation"]["request_hash"]
