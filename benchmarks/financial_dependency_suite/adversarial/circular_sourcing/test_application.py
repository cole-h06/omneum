import pytest

import benchmarks.financial_dependency_suite.adversarial.circular_sourcing.application as app


@pytest.mark.anyio
async def test_application_run(monkeypatch):
    candidates = [
        {"source": "independent_a", "text": "The request timeout is 60 seconds."},
        {"source": "independent_b", "text": "The request timeout is 60 seconds."},
        {"source": "independent_c", "text": "The request timeout is 60 seconds."},
        {"source": "circular_a", "text": "The request timeout is 30 seconds."},
        {"source": "circular_b", "text": "The request timeout is 30 seconds."},
        {"source": "circular_c", "text": "The request timeout is 30 seconds."},
    ]

    monkeypatch.setattr(
        app,
        "case_data",
        lambda: (candidates, (), {}),
    )

    def local_select(query, candidates, *, top_n):
        return {
            "selected": candidates[:top_n],
            "latency_seconds": 0.01,
        }

    monkeypatch.setattr(app, "select_vector", local_select)
    monkeypatch.setattr(app, "select_bge", local_select)
    monkeypatch.setattr(app, "select_cohere", local_select)

    async def braid_select(
        candidates,
        observations,
        source_ids,
        *,
        estimator,
        top_n,
    ):
        return {
            "selected": candidates[:top_n],
            "latency_seconds": 0.01,
            "evaluation": object(),
            "model": "BRAID",
        }

    monkeypatch.setattr(app, "select_braid", braid_select)

    async def llm_select(
        query,
        candidates,
        *,
        provider,
        model,
        top_n,
    ):
        return {
            "selection": {
                "selected": candidates[:top_n],
                "latency_seconds": 0.01,
            },
            "failure": None,
        }

    monkeypatch.setattr(
        app,
        "select_llm_safe",
        llm_select,
    )

    async def fake_generate(
        query,
        selected,
        *,
        provider,
        model,
    ):
        return {
            "text": "The payments-api request timeout is 60 seconds.",
            "provider": provider,
            "model": model,
            "latency_seconds": 0.02,
            "input_tokens": 100,
            "output_tokens": 20,
        }

    monkeypatch.setattr(app, "generate_answer", fake_generate)

    result = await app.run()

    assert result["benchmark"] == "circular_sourcing"
    assert result["context_budget"] == 3
    assert len(result["methods"]) == 7

    for method in result["methods"].values():
        assert len(method["selected"]) == 3
        assert method["answer_score"] == "correct"
