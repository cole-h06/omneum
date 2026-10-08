import pytest

import benchmarks.financial_dependency_suite.adversarial.source_dependence.application as app


@pytest.mark.anyio
async def test_application_run(monkeypatch):
    candidates = [
        {"source": "a", "text": "Arm revenue was $2.679 billion."},
        {"source": "b", "text": "Arm revenue was $2.679 billion."},
        {"source": "c", "text": "Arm revenue was $2.679 billion."},
        {"source": "d", "text": "Arm revenue was $3.2 billion."},
        {"source": "e", "text": "Arm revenue was $3.2 billion."},
        {"source": "f", "text": "Arm revenue was $3.2 billion."},
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
    monkeypatch.setattr(
        app,
        "select_cohere_safe",
        lambda query, candidates, *, top_n: {
            "selection": local_select(
                query,
                candidates,
                top_n=top_n,
            ),
            "failure": None,
        },
    )

    async def omneum_select(
        query,
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
            "model": "Omneum",
        }

    monkeypatch.setattr(app, "select_omneum_reranked", omneum_select)

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
            "text": "Arm revenue was $2.679 billion.",
            "provider": provider,
            "model": model,
            "latency_seconds": 0.02,
            "input_tokens": 100,
            "output_tokens": 20,
        }

    async def fake_generate_safe(
        query,
        selected,
        *,
        provider,
        model,
    ):
        return {
            "generation": await fake_generate(
                query,
                selected,
                provider=provider,
                model=model,
            ),
            "failure": None,
        }

    monkeypatch.setattr(
        app,
        "generate_answer_safe",
        fake_generate_safe,
    )

    result = await app.run()

    assert result["benchmark"] == "source_dependence"
    assert result["context_budget"] == 3
    assert len(result["methods"]) == 7

    for method in result["methods"].values():
        assert len(method["selected"]) == 3
        assert method["answer_score"] == "correct"
