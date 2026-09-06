from benchmarks.financial_dependency_suite.application_comparison import (
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

import benchmarks.financial_dependency_suite.application_comparison as app


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
async def test_braid_selection(monkeypatch):
    async def fake_evaluate(mapped, *, estimator):
        return object()

    def fake_map(candidates, observations, source_ids):
        return candidates

    def fake_select(mapped, evaluation, *, top_n):
        return [
            {"retrieved": candidate}
            for candidate in mapped[:top_n]
        ]

    import benchmarks.financial_dependency_suite.braid_rag as braid

    monkeypatch.setattr(
        braid,
        "evaluate_context",
        fake_evaluate,
    )
    monkeypatch.setattr(
        braid,
        "map_observations",
        fake_map,
    )
    monkeypatch.setattr(
        braid,
        "select_context",
        fake_select,
    )

    result = await app.select_braid(
        CANDIDATES,
        observations=(),
        source_ids={},
        estimator=None,
        top_n=2,
    )

    assert_valid_selection(result, top_n=2)
    assert result["model"] == "BRAID"
