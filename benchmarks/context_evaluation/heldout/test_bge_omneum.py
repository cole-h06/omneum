"""Additive reliability path contracts, with no model or provider calls."""

import asyncio
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from benchmarks.context_evaluation import application_comparison as app
from benchmarks.context_evaluation import omneum_rag as omneum
from benchmarks.context_evaluation import naive_rag
from . import runner
from .artifacts import checkpoint
from .additive_methods import method_by_name
from .methods import METHODS
from .test_runner import truth


def claim(support, *supporters, is_attribute_max_support=True):
    return NS(
        claim="value",
        support=support,
        is_attribute_max_support=is_attribute_max_support,
        supporting_sources=[
            NS(source=source, contribution=contribution)
            for source, contribution in supporters
        ],
    )


def evaluation(*pairs, threshold=0.5):
    return NS(
        claim_support=[],
        source_reliability=[],
        pairwise_dependencies=[
            NS(source_a=a, source_b=b, dependency=dependency)
            for a, b, dependency in pairs
        ],
        dependency_cluster_threshold=threshold,
    )


def test_omneum_preserves_relevance_without_dependencies():
    mapped = [
        {"retrieved": {"source": source, "text": source, "score": score},
         "observation": NS(source=source)}
        for source, score in (("a", 100), ("b", 99), ("c", 98), ("d", 97))
    ]

    result = evaluation()
    result.claim_support = [
        claim(1.0, ("a", 0.2), ("b", 0.1), ("c", 0.8), ("d", 0.4))
    ]

    selected = omneum.select_reliable_context(mapped, result, top_n=3)

    assert [item["retrieved"]["source"] for item in selected] == ["a", "b", "c"]


def test_relevance_order_without_dependencies():
    mapped = [
        {"retrieved": {"source": source}, "observation": NS(source=source)}
        for source in ("a", "b", "c")
    ]

    selected = omneum.select_reliable_context(
        mapped,
        evaluation(threshold=0.5),
        top_n=2,
    )

    assert [item["retrieved"]["source"] for item in selected] == ["a", "b"]


@pytest.mark.parametrize("count,budget,depth", [(7, 2, 4), (3, 2, 3), (1, 1, 1)])
def test_paired_pipeline_and_persisted_telemetry(monkeypatch, tmp_path, count, budget, depth):
    import json

    candidates = [{"source": f"s{i}", "text": str(i)} for i in range(count)]
    from omneum import Source

    sources = [
        Source(kind="web_document", identifier=f"https://example.com/s{i}")
        for i in range(count)
    ]
    observations = [
        NS(
            observation_id=f"o{i}",
            source=sources[i],
            upstream_sources=(),
            cited_sources=(),
            parent_observation_ids=(),
        )
        for i in range(count)
    ]
    benchmark_case = NS(question="question", context_budget=budget)
    monkeypatch.setattr(runner, "application_candidates", lambda case: candidates)
    monkeypatch.setattr(runner, "build_observations", lambda case: (
        observations,
        {source: f"s{i}" for i, source in enumerate(sources)},
    ))
    # Exercise the real BGE envelope and Omneum mapping/selection with fixed clocks.
    ticks = iter([0, 2, 2, 5])
    monkeypatch.setattr(app, "perf_counter", lambda: next(ticks))
    relevance_selected = candidates[::-1][:depth]

    def rerank(query, pool, *, top_n):
        assert query == benchmark_case.question
        assert pool is candidates
        assert top_n == depth
        return relevance_selected

    async def evaluate(mapped, *, estimator):
        assert [item["observation"] for item in mapped] == observations[::-1][:depth]
        source_by_id = {
            f"s{i}": source
            for i, source in enumerate(sources)
        }
        return NS(
            evaluation_latency_ms=125,
            source_reliability=[
                NS(source=source_by_id[item["source"]], reliability=1.0)
                for item in relevance_selected
            ],
            claim_support=[
                claim(i + 1, (source_by_id[item["source"]], i + 1))
                for i, item in enumerate(relevance_selected)
            ],
            pairwise_dependencies=[],
            dependency_cluster_threshold=0.5,
        )

    generated = []

    async def generate(query, documents, **kwargs):
        generated.append(documents)
        return {"generation": {"text": "42", "latency_seconds": 1}, "failure": None}

    monkeypatch.setattr(app, "rerank_bge", rerank)
    monkeypatch.setattr(omneum, "evaluate_context", evaluate)
    monkeypatch.setattr(runner, "generate_answer_safe", generate)
    result = asyncio.run(runner.run_method(
        "bge_omneum", benchmark_case, truth(),
        generator_provider="anthropic", generator_model="generator",
    ))
    assert len(result["selected"]) == budget
    assert set(result["selected"]).issubset(
        {item["source"] for item in relevance_selected}
    )
    assert generated == [result["selection"]["selected"]]
    path = tmp_path / "paired.jsonl"
    checkpoint(path, [result])
    saved = json.loads(path.read_text())
    selection = saved["selection"]
    assert selection["model"] == "Omneum"
    assert selection["relevance_model"] == "BAAI/bge-reranker-v2-m3"
    assert selection["relevance_depth"] == depth
    assert selection["bge_latency_seconds"] == 2
    assert selection["omneum_latency_seconds"] == 3
    assert selection["cold_integration_latency_seconds"] == 3
    assert selection["evaluation_latency_seconds"] == .125
    assert selection["latency_seconds"] == 5
    assert saved["end_to_end_latency_seconds"] == 6
    assert saved["selected"] == result["selected"]
    assert selection["relevance_selected_sources"] == [item["source"] for item in relevance_selected]


def test_frozen_bge_and_omneum_routes(monkeypatch):
    candidates = [{"source": "a", "text": "A"}, {"source": "b", "text": "B"}]
    observations = [NS(source=item["source"]) for item in candidates]
    case = NS(question="question", context_budget=1)
    monkeypatch.setattr(runner, "application_candidates", lambda case: candidates)
    monkeypatch.setattr(runner, "build_observations", lambda case: (observations, {"a": "a", "b": "b"}))

    def rerank(query, pool, *, top_n):
        assert pool is candidates
        assert top_n == 1
        return pool[:top_n]

    async def evaluate(mapped, *, estimator):
        assert [item["observation"] for item in mapped] == observations
        return NS(claim_support=[claim(10, ("a", 10)), claim(1, ("b", 1))])

    def relevance(query, documents, *, top_k):
        assert query == case.question
        assert top_k == len(candidates)
        return [{"source": "a", "score": 0}, {"source": "b", "score": 1}]

    monkeypatch.setattr(app, "rerank_bge", rerank)
    monkeypatch.setattr(omneum, "evaluate_context", evaluate)
    monkeypatch.setattr(naive_rag, "rank_documents", relevance)
    baseline = asyncio.run(runner.run_selection("bge", case))
    assert baseline["selected"] == candidates[:1]
    assert baseline["model"] == "BAAI/bge-reranker-v2-m3"
    assert set(baseline) == {"selected", "model", "latency_seconds"}
    frozen = asyncio.run(runner.run_selection("omneum", case))
    assert frozen["model"] == "Omneum"
    assert frozen["selected"] == candidates[1:]  # Frozen 0.6 relevance + 0.4 structural.
    assert "bge_omneum" not in {method.name for method in METHODS}
    assert method_by_name("bge_omneum").model == "Omneum"


def test_opt_in_paired_schedule(monkeypatch, tmp_path):
    import json
    from . import run_benchmark as driver

    discovered = driver.discover_cases(driver.CASES_DIR)[:1]
    monkeypatch.setattr(driver, "discover_cases", lambda path: discovered)
    monkeypatch.setattr(driver, "warm_local_models", lambda *args: None)
    calls = []

    async def selection(method, case, **kwargs):
        calls.append(method)
        return {"selected": runner.application_candidates(case)[:case.context_budget],
                "latency_seconds": 0.1}

    async def generate(*args, **kwargs):
        return {"generation": {"text": "fixture", "latency_seconds": .2}, "failure": None}

    monkeypatch.setattr(runner, "run_selection", selection)
    monkeypatch.setattr(runner, "generate_answer_safe", generate)
    methods = tuple(map(method_by_name, ("bge", "bge_omneum")))
    directory = asyncio.run(driver.run_benchmark(
        results_dir=tmp_path, trials=1, identifier="paired", methods=methods,
    ))
    manifest = json.loads((directory / "manifest.json").read_text())
    assert calls == ["bge", "bge_omneum"]
    assert [item["name"] for item in manifest["checkpoint_contract"]["methods"]] == calls
    assert manifest["models"]["bge_omneum"] == "Omneum"
    records = [json.loads(line) for line in (directory / "results.jsonl").read_text().splitlines()]
    assert [record["method"] for record in records] == calls


def test_paired_cli(monkeypatch, tmp_path, capsys):
    import sys
    from . import run_benchmark as driver

    async def run(**kwargs):
        assert [method.name for method in kwargs["methods"]] == ["bge", "bge_omneum"]
        return tmp_path

    monkeypatch.setattr(sys, "argv", ["heldout", "--methods", "bge", "bge_omneum"])
    monkeypatch.setattr(driver, "run_benchmark", run)
    driver.main()
    assert str(tmp_path) in capsys.readouterr().out


def test_claude_baseline_with_existing_bge_omneum_pipeline(monkeypatch, tmp_path, baseline_results):
    import json
    from benchmarks.context_evaluation import clients
    from . import run_benchmark as driver

    baseline = baseline_results
    original = {row["case_id"]: row for row in map(json.loads, baseline.read_text().splitlines())
                if row["method"] == "anthropic"}
    cases = driver.discover_cases(driver.CASES_DIR)
    calls = {"bge": 0, "omneum": 0, "generator": 0, "warmup": 0}

    def warmup(query, pool):
        calls["warmup"] += 1

    def bge(query, pool, *, top_n):
        _, _, case, _ = cases[calls["bge"]]
        assert query == case.question
        assert pool == runner.application_candidates(case)
        assert top_n == min(len(pool), 2 * case.context_budget)
        calls["bge"] += 1
        return {"selected": pool[:top_n], "model": "BAAI/bge-reranker-v2-m3",
                "latency_seconds": .2}

    async def reliability(pool, observations, source_ids, *, estimator, top_n):
        _, _, case, _ = cases[calls["omneum"]]
        assert pool == runner.application_candidates(case)[:min(len(case.candidates), 2 * case.context_budget)]
        assert (observations, source_ids) == runner.build_observations(case)
        assert estimator == runner.estimator_config()
        assert top_n == case.context_budget
        calls["omneum"] += 1
        return {"selected": pool[:top_n], "model": "Omneum", "latency_seconds": .3,
                "cold_integration_latency_seconds": .3, "evaluation_latency_seconds": .05}

    async def anthropic(prompt, model, max_tokens, *, response_schema=None):
        _, _, case, _ = cases[calls["generator"]]
        documents = runner.application_candidates(case)[:case.context_budget]
        context = "\n\n".join(f"Source: {item['source']}\n{item['text']}" for item in documents)
        assert prompt == f"Answer the question using only the sources below.\n\nQuestion:\n\n{case.question}\n\nSources:\n\n{context}\n\nGive a concise answer and identify which sources support it.\n"
        assert model == "claude-sonnet-5-5"
        assert max_tokens == 1024
        assert response_schema is None
        calls["generator"] += 1
        return {"text": "fixture", "provider": "anthropic", "model": model,
                "latency_seconds": .4, "input_tokens": 11, "output_tokens": 7}

    async def no_claude_judge(*args, **kwargs):
        pytest.fail("frozen Claude baseline must never be regenerated")

    monkeypatch.setattr(driver, "warm_local_models", warmup)
    monkeypatch.setattr(runner, "select_bge", bge)
    monkeypatch.setattr(runner, "select_omneum", reliability)
    monkeypatch.setattr(runner, "select_llm_safe", no_claude_judge)
    monkeypatch.setattr(clients, "_generate_anthropic", anthropic)
    directory = asyncio.run(driver.run_benchmark(
        results_dir=tmp_path, trials=1, identifier="claude-bge-omneum",
        methods=tuple(map(method_by_name, ("anthropic", "bge_omneum"))),
        baseline_results=baseline,
    ))
    records = list(map(json.loads, (directory / "results.jsonl").read_text().splitlines()))
    assert len(records) == 48
    assert calls == {"bge": 24, "omneum": 24, "generator": 24, "warmup": 1}
    assert all(row == original[row["case_id"]] for row in records if row["method"] == "anthropic")
    for row in (row for row in records if row["method"] == "bge_omneum"):
        selection = row["selection"]
        assert selection["bge_latency_seconds"] == .2
        assert selection["omneum_latency_seconds"] == .3
        assert selection["evaluation_latency_seconds"] == .05
        assert selection["cold_integration_latency_seconds"] == .3
        assert selection["latency_seconds"] == .5
        assert row["generation"]["latency_seconds"] == .4
        assert row["generation"]["input_tokens"] == 11
        assert row["generation"]["output_tokens"] == 7
        assert row["end_to_end_latency_seconds"] == pytest.approx(.9)
    manifest = json.loads((directory / "manifest.json").read_text())
    assert set(manifest["selection_pipeline"]) == {"bge_omneum"}
    pipeline = manifest["selection_pipeline"]["bge_omneum"]
    assert pipeline["relevance_model"] == "BAAI/bge-reranker-v2-m3"
    assert pipeline["relevance_shortlist"] is True
    assert pipeline["generator_provider"] == "anthropic"
    assert pipeline["generator_model"] == "claude-sonnet-5-5"



@pytest.mark.parametrize("budget,expected", [
    (2, ["current_a", "stale_a"]),
    (3, ["current_a", "current_b", "stale_a"]),
])
def test_structural_claim_tie(budget, expected):
    mapped = [
        {
            "retrieved": {"source": "current_a", "reranker_score": 0.99},
            "observation": NS(source="current_a"),
        },
        {
            "retrieved": {"source": "current_b", "reranker_score": 0.98},
            "observation": NS(source="current_b"),
        },
        {
            "retrieved": {"source": "stale_a", "reranker_score": 0.40},
            "observation": NS(source="stale_a"),
        },
    ]

    result = evaluation(threshold=0.5)
    result.source_reliability = [
        NS(source="current_a", reliability=0.5),
        NS(source="current_b", reliability=0.5),
        NS(source="stale_a", reliability=0.5),
    ]
    result.claim_support = [
        NS(
            claim=NS(
                entity_namespace="test",
                entity="seat-count",
                attribute="value",
                value=1284,
            ),
            support=0.5,
            is_attribute_max_support=True,
            supporting_sources=(
                NS(source="current_a"),
                NS(source="current_b"),
            ),
        ),
        NS(
            claim=NS(
                entity_namespace="test",
                entity="seat-count",
                attribute="value",
                value=1190,
            ),
            support=0.5,
            is_attribute_max_support=True,
            supporting_sources=(NS(source="stale_a"),),
        ),
    ]
    result.pairwise_dependencies = [
        NS(source_a="current_a", source_b="current_b", dependency=1.0),
        NS(source_a="current_a", source_b="stale_a", dependency=0.0),
        NS(source_a="current_b", source_b="stale_a", dependency=0.0),
    ]

    selected = omneum.select_reliable_context(mapped, result, top_n=budget)

    assert [item["retrieved"]["source"] for item in selected] == expected


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("name,scores,quality,support,expected", [
    (
        "coding_config_conflict",
        {"readme": .991787, "deployment_config": .807947,
         "ci_config": .053020, "test_output": .024326},
        {"readme": .215, "deployment_config": .215,
         "ci_config": .355, "test_output": .215},
        .1075,
        ["readme", "deployment_config"],
    ),
    (
        "research_syndicated_reporting",
        {"original_report": .994735, "news_article": .978914,
         "dataset": .971956, "news_article_2": .953672,
         "news_article_3": .948063, "web_page": .936073},
        {},
        1 / 14,
        ["original_report", "news_article", "dataset"],
    ),
])
def test_case_claim_tie(monkeypatch, reverse, name, scores, quality, support, expected):
    from .loader import load_case, application_candidates, build_observations

    case = load_case(Path(__file__).parent / "cases" / name / "case.json")
    observations, source_ids = build_observations(case)
    candidates = {
        item["source"]: item
        for item in application_candidates(case)
    }
    pool = [
        {**candidates[source], "reranker_score": score}
        for source, score in scores.items()
    ]

    async def evaluate(mapped, *, estimator):
        sources = [item["observation"].source for item in mapped]
        result = evaluation()
        result.evaluation_latency_ms = 0
        result.source_reliability = [
            NS(source=source, reliability=quality.get(source_ids[source], 1 / 7))
            for source in sources
        ]
        claims = {}
        for item in mapped:
            observation = item["observation"]
            claims.setdefault(observation.claim, []).append(observation.source)
        result.claim_support = [
            NS(
                claim=value,
                support=support,
                is_attribute_max_support=True,
                supporting_sources=[NS(source=source) for source in supporters],
            )
            for value, supporters in claims.items()
        ]
        tied = [claim for claim in result.claim_support if claim.support == support]
        assert len(tied) >= 2
        if name == "research_syndicated_reporting":
            assert "primary_record" in {source_ids[source] for source in sources}
        if reverse:
            result.claim_support.reverse()
        return result

    monkeypatch.setattr(omneum, "evaluate_context", evaluate)
    selected = asyncio.run(app.select_omneum(
        pool, observations, source_ids, estimator=None, top_n=case.context_budget,
    ))

    assert [item["source"] for item in selected["selected"]] == expected


def test_dependency_preserves_competing_context():
    mapped = [
        {
            "retrieved": {
                "source": source,
                "text": source,
                "reranker_score": relevance,
            },
            "observation": NS(source=source),
        }
        for source, relevance in (
            ("warehouse", 0.99),
            ("api", 0.98),
            ("metric_store", 0.97),
            ("stale_report", 1.0),
        )
    ]

    result = evaluation(
        ("warehouse", "api", 1.0),
        ("warehouse", "metric_store", 1.0),
        ("api", "metric_store", 1.0),
        threshold=0.5,
    )
    result.source_reliability = [
        NS(source="warehouse", reliability=0.5),
        NS(source="api", reliability=0.5),
        NS(source="metric_store", reliability=0.5),
        NS(source="stale_report", reliability=0.5),
    ]

    winning = NS(
        entity_namespace="service",
        entity="meridian",
        attribute="seat_count",
        value=1284,
    )
    stale = NS(
        entity_namespace="service",
        entity="meridian",
        attribute="seat_count",
        value=1190,
    )

    result.claim_support = [
        NS(
            claim=winning,
            support=1.0,
            is_attribute_max_support=True,
            supporting_sources=[
                NS(source="warehouse", contribution=0.1),
                NS(source="api", contribution=0.1),
                NS(source="metric_store", contribution=0.1),
            ],
        ),
        NS(
            claim=stale,
            support=0.5,
            is_attribute_max_support=False,
            supporting_sources=[
                NS(source="stale_report", contribution=0.5),
            ],
        ),
    ]

    selected = omneum.select_reliable_context(mapped, result, top_n=3)

    assert [item["retrieved"]["source"] for item in selected] == [
        "stale_report",
        "warehouse",
        "api",
    ]
