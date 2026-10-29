from benchmarks.context_selection.application_comparison import (
    select_bge,
    select_vector,
)


QUERY = "What is the current retention period for payments-api?"

CANDIDATES = [
    {
        "source": "current",
        "text": "The payments-api retention period is 90 days.",
    },
    {
        "source": "stale",
        "text": "The payments-api retention period is 30 days.",
    },
    {
        "source": "timeout",
        "text": "The payments-api request timeout is 60 seconds.",
    },
    {
        "source": "deployment",
        "text": "The service runs in three availability zones.",
    },
]


def assert_valid_selection(result, *, top_n):
    selected = result["selected"]

    assert len(selected) == top_n

    candidate_sources = {
        candidate["source"]
        for candidate in CANDIDATES
    }
    selected_sources = {
        item["source"]
        for item in selected
    }

    assert selected_sources <= candidate_sources
    assert len(selected_sources) == top_n


def test_vector_selection():
    result = select_vector(
        QUERY,
        CANDIDATES,
        top_n=2,
    )

    assert_valid_selection(result, top_n=2)


def test_bge_selection():
    result = select_bge(
        QUERY,
        CANDIDATES,
        top_n=2,
    )

    assert_valid_selection(result, top_n=2)

import pytest

import benchmarks.context_selection.application_comparison as app


def test_cohere_selection(monkeypatch):
    def fake_rerank(query, candidates, *, top_n):
        return {
            "selected": candidates[:top_n],
            "model": "rerank-v4.0-pro",
            "latency_seconds": 0.1,
        }

    monkeypatch.setattr(
        app,
        "rerank_cohere",
        fake_rerank,
    )

    result = app.select_cohere(
        QUERY,
        CANDIDATES,
        top_n=2,
    )

    assert_valid_selection(result, top_n=2)
    assert result["model"] == "rerank-v4.0-pro"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("provider", "model"),
    app.LLM_SELECTORS,
)
async def test_llm_selection(
    monkeypatch,
    provider,
    model,
):
    async def fake_generate(
        prompt,
        *,
        provider=None,
        model=None,
        max_tokens=1024,
        response_schema=None,
    ):
        return {
            "text":
                '{"selected_sources": ["current", "stale"]}',
            "provider": provider,
            "model": model,
            "input_tokens": 100,
            "output_tokens": 10,
            "latency_seconds": 0.2,
        }

    monkeypatch.setattr(
        app,
        "generate",
        fake_generate,
    )

    result = await app.select_llm(
        QUERY,
        CANDIDATES,
        provider=provider,
        model=model,
        top_n=2,
    )

    assert result["parse_error"] is None
    assert_valid_selection(result, top_n=2)


@pytest.mark.anyio
async def test_llm_selector_rejects_invalid_selection(monkeypatch):
    async def fake_generate(
        prompt,
        *,
        provider=None,
        model=None,
        max_tokens=1024,
        response_schema=None,
    ):
        return {
            "text":
                '{"selected_sources": ["current", "not_a_source"]}',
            "provider": provider,
            "model": model,
            "input_tokens": 100,
            "output_tokens": 10,
            "latency_seconds": 0.2,
        }

    monkeypatch.setattr(
        app,
        "generate",
        fake_generate,
    )

    result = await app.select_llm(
        QUERY,
        CANDIDATES,
        provider="anthropic",
        model="claude-sonnet-5",
        top_n=2,
    )

    assert result["selected"] == []
    assert result["parse_error"] is not None


@pytest.mark.anyio
async def test_omneum_selection(monkeypatch):
    async def fake_evaluate(mapped, *, estimator):
        return object()

    def fake_map(candidates, observations, source_ids):
        return candidates

    def fake_select(query, mapped, evaluation, *, top_n):
        return [
            {"retrieved": candidate}
            for candidate in mapped[:top_n]
        ]

    import benchmarks.context_selection.omneum_rag as omneum

    monkeypatch.setattr(
        omneum,
        "evaluate_context",
        fake_evaluate,
    )
    monkeypatch.setattr(
        omneum,
        "map_observations",
        fake_map,
    )
    monkeypatch.setattr(
        omneum,
        "select_context",
        fake_select,
    )

    result = await app.select_omneum_reranked(
        QUERY,
        CANDIDATES,
        observations=(),
        source_ids={},
        estimator=None,
        top_n=2,
    )

    assert_valid_selection(result, top_n=2)
    assert result["model"] == "Omneum"



def test_provenance_context():
    from datetime import datetime, timezone
    from dataclasses import dataclass

    from benchmarks.context_selection.application_comparison import (
        provenance_context,
    )

    @dataclass(frozen=True)
    class Source:
        kind: str
        identifier: str

    source_a = Source(
        "web_document",
        "https://example.com/a",
    )
    source_b = Source(
        "web_document",
        "https://example.com/b",
    )

    class Observation:
        source = source_a
        observation_id = "assertion-a"
        observed_at = datetime(
            2026, 9, 11, tzinfo=timezone.utc
        )
        source_modified_at = datetime(
            2026, 9, 10, tzinfo=timezone.utc
        )
        upstream_sources = (source_b,)
        cited_sources = (source_b,)
        parent_observation_ids = ("parent-a",)

    result = provenance_context(
        [{"source": "source_a", "text": "A"}],
        [Observation()],
        {
            source_a: "source_a",
            source_b: "source_b",
        },
    )

    assert set(result) == {"source_a"}
    assert result["source_a"][0] == {
        "assertion_id": "assertion-a",
        "observed_at": "2026-09-11T00:00:00+00:00",
        "source_modified_at": "2026-09-10T00:00:00+00:00",
        "upstream_sources": [
            {
                "kind": "web_document",
                "identifier": "https://example.com/b",
            }
        ],
        "cited_sources": [
            {
                "kind": "web_document",
                "identifier": "https://example.com/b",
            }
        ],
        "parent_assertion_ids": ["parent-a"],
    }


def test_llm_provenance_selection(monkeypatch):
    import asyncio

    import benchmarks.context_selection.application_comparison as app

    candidates = [
        {"source": "source_a", "text": "A"},
        {"source": "source_b", "text": "B"},
    ]

    async def fake_generate(prompt, *, provider, model, response_schema):
        assert response_schema == app.SELECTION_SCHEMA
        assert "Structured provenance:" in prompt
        return {
            "text": '{"selected_sources": ["source_b"]}',
            "provider": provider,
            "model": model,
            "latency_seconds": 0.1,
            "input_tokens": 10,
            "output_tokens": 5,
        }

    monkeypatch.setattr(app, "generate", fake_generate)

    result = asyncio.run(
        app.select_llm_provenance(
            "question",
            candidates,
            [],
            {},
            provider="anthropic",
            model="test-model",
            top_n=1,
        )
    )

    assert result["selected"] == [candidates[1]]
    assert result["parse_error"] is None
    assert result["raw_output"] == (
        '{"selected_sources": ["source_b"]}'
    )
