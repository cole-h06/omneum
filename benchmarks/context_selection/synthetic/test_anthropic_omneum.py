"""Claude + Omneum contracts; all provider and evaluator calls are stubbed."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from benchmarks.context_selection.synthetic import additive_runner as runner
from benchmarks.context_selection.synthetic.additive_methods import method_by_name
from benchmarks.context_selection.synthetic.baseline_reuse import load_anthropic_baseline
from benchmarks.context_selection.synthetic.run_benchmark import discover_cases
from benchmarks.context_selection.synthetic.test_runner import truth
from benchmarks.context_selection.synthetic.loader import load_case




@pytest.mark.parametrize("count,budget", [(10, 3), (3, 2), (1, 1)])
def test_omneum_uses_full_pool_without_claude_selector(monkeypatch, count, budget):
    candidates = [{"source": f"s{i}", "text": f"candidate {i}"} for i in range(count)]
    case = NS(question="question", context_budget=budget)
    final = candidates[::-1][:budget]
    truth_data = truth()
    generated, evaluated = [], []
    observations, source_ids = (), {item["source"]: item["source"] for item in candidates}

    monkeypatch.setattr(runner, "application_candidates", lambda _: candidates)
    monkeypatch.setattr(runner, "build_observations", lambda _: (observations, source_ids))

    async def claude(*args, **kwargs):
        pytest.fail("anthropic_omneum must not invoke the Anthropic relevance selector")

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

    monkeypatch.setattr(runner, "select_llm_safe", claude, raising=False)
    monkeypatch.setattr(runner.frozen, "select_llm_safe", claude)
    monkeypatch.setattr(runner, "select_omneum", omneum)
    monkeypatch.setattr(runner, "generate_answer_safe", generate)
    result = asyncio.run(runner.run_method(
        "anthropic_omneum", case, truth_data, provider="anthropic",
        model="claude-sonnet-5-5", generator_provider="anthropic",
        generator_model="claude-sonnet-5-5",
    ))

    assert evaluated == [(candidates, observations, source_ids, budget)]
    assert result["selected"] == [item["source"] for item in final]
    assert generated == [("question", final, "anthropic", "claude-sonnet-5-5")]
    assert len(final) == budget
    assert result["selection_score"] == runner.score_selection(result["selected"], truth_data)
    assert result["answer_score"] == runner.score_answer("answer 42", truth_data)
    assert result["selection"]["candidate_pool_size"] == count
    assert result["selection"]["candidate_pool_sources"] == [item["source"] for item in candidates]
    assert result["selection"]["evaluator_provider"] == "local"
    assert result["selection"]["evaluator_model"] == "Omneum"
    assert result["selection"]["evaluator_input_tokens"] == 0
    assert result["selection"]["evaluator_output_tokens"] == 0
    assert result["selection"]["evaluator_latency_seconds"] == .1
    assert result["selection"]["evaluation_latency_seconds"] == .1
    assert result["selection"]["cold_integration_latency_seconds"] == .4
    assert result["generation"]["input_tokens"] == 11
    assert result["generation"]["output_tokens"] == 4
    assert result["selection"]["request_hash"]
    assert result["generation"]["request_hash"]
    assert result["selection"]["latency_seconds"] == pytest.approx(.4)
    assert result["end_to_end_latency_seconds"] == pytest.approx(.9)
    assert result["inference_cost"] == {"usd": None, "availability": "no_pricing_defined"}


def test_baseline_compatibility(baseline_results):
    discovered = discover_cases(Path(__file__).with_name("cases"))
    reused, metadata = load_anthropic_baseline(
        baseline_results, discovered, generator_model="claude-sonnet-5-5",
    )
    original = [json.loads(line) for line in baseline_results.read_text().splitlines()
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


def test_selection_underfill(monkeypatch):
    candidates = [{"source": f"s{i}", "text": str(i)} for i in range(4)]
    case = NS(question="question", context_budget=2)
    monkeypatch.setattr(runner, "application_candidates", lambda _: candidates)
    monkeypatch.setattr(runner, "build_observations", lambda _: ([], {}))
    async def underfilled(*args, **kwargs):
        return {"selected": candidates[:1], "model": "Omneum", "latency_seconds": .2}
    async def no_generation(*args, **kwargs):
        pytest.fail("must not answer from fewer than the final context budget")
    monkeypatch.setattr(runner, "select_omneum", underfilled)
    monkeypatch.setattr(runner, "generate_answer_safe", no_generation)
    result = asyncio.run(runner.run_method(
        "anthropic_omneum", case, truth(), generator_provider="anthropic",
        generator_model="claude-sonnet-5-5",
    ))
    assert result["answer_score"] == "selection_failure"
    assert result["failure_type"] == "omneum_selection_contract"
    assert result["selection"]["request_hash"]


def test_generation_failure_metadata(monkeypatch):
    candidates = [{"source": f"s{i}", "text": str(i)} for i in range(4)]
    case = NS(question="question", context_budget=2)
    monkeypatch.setattr(runner, "application_candidates", lambda _: candidates)
    monkeypatch.setattr(runner, "build_observations", lambda _: ([], {}))
    async def omneum(*args, top_n, **kwargs):
        return {"selected": candidates[:top_n], "model": "Omneum", "latency_seconds": .2}
    async def failed_generation(*args, **kwargs):
        return {"failure": {"answer": None, "answer_score": "generation_failure",
                            "failure_type": "provider_error", "generation": None}}
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
def test_baseline_mismatch_is_rejected(tmp_path, mismatch, baseline_results):
    import shutil

    source_dir = baseline_results.parent
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


def test_baseline_reuse(monkeypatch, tmp_path, baseline_results):
    from benchmarks.context_selection.synthetic import run_benchmark as driver

    discovered = driver.discover_cases(driver.CASES_DIR)
    methods = (method_by_name("anthropic"), method_by_name("anthropic_omneum"))
    calls = {"evaluator": 0, "generator": 0, "omneum": 0}

    async def evaluator(query, candidates, *, provider, model, top_n):
        calls["evaluator"] += 1
        pytest.fail("paired baseline reuse must not call the Claude selector")

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
    monkeypatch.setattr(runner, "select_llm_safe", evaluator, raising=False)
    monkeypatch.setattr(runner.frozen, "select_llm_safe", evaluator)
    monkeypatch.setattr(runner, "select_omneum", omneum)
    monkeypatch.setattr(runner, "generate_answer_safe", generator)
    directory = asyncio.run(driver.run_benchmark(
        results_dir=tmp_path, trials=1, identifier="claude-paired",
        methods=methods, baseline_results=baseline_results,
    ))
    rows = [json.loads(line) for line in (directory / "results.jsonl").read_text().splitlines()]
    original = {row["case_id"]: row for row in
                (json.loads(line) for line in baseline_results.read_text().splitlines())
                if row.get("method") == "anthropic"}
    assert len(rows) == 48
    assert calls == {"evaluator": 0, "generator": 24, "omneum": 24}
    assert all(row == original[row["case_id"]] for row in rows if row["method"] == "anthropic")
    assert all(row["method"] in {"anthropic", "anthropic_omneum"} for row in rows)
    output_manifest = json.loads((directory / "manifest.json").read_text())
    assert output_manifest["baseline_reuse"]["reused_records"] == 24
    pipeline = output_manifest["selection_pipeline"]["anthropic_omneum"]
    assert pipeline["relevance_shortlist"] is False
    assert pipeline["evaluator_provider"] == "local"
    assert output_manifest["models"]["anthropic_omneum"] == "Omneum"
    assert pipeline["generator_model"] == "claude-sonnet-5-5"
    paired = next(row for row in rows if row["method"] == "anthropic_omneum")
    assert paired["selection"]["evaluator_input_tokens"] == 0
    assert paired["selection"]["evaluator_output_tokens"] == 0
    assert paired["selection"]["evaluator_raw_output"] is None
    assert paired["selection"]["request_hash"]
    assert paired["generation"]["request_hash"]
