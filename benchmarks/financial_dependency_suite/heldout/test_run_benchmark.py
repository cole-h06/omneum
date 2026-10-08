import json

import pytest

from benchmarks.financial_dependency_suite.heldout.run_benchmark import (
    discover_cases,
)


def test_discover_cases(tmp_path):
    directory = tmp_path / "case_a"
    directory.mkdir()

    case = {
        "id": "case_a",
        "domain": "test",
        "question": "What is the value?",
        "context_budget": 1,
        "candidates": [],
    }

    truth = {
        "case_id": "case_a",
        "answer": "42",
        "supporting_sources": [],
        "scoring": {
            "required": ["42"],
            "forbidden": [],
        },
    }

    (directory / "case.json").write_text(
        json.dumps(case)
    )
    (directory / "ground_truth.json").write_text(
        json.dumps(truth)
    )

    discovered = discover_cases(tmp_path)

    assert len(discovered) == 1
    assert discovered[0][2].case_id == "case_a"
    assert discovered[0][3].case_id == "case_a"


@pytest.mark.parametrize("provider_fails", [False, True])
def test_smoke_real_llm_envelope_and_failure_continuation(
    monkeypatch, tmp_path, caplog, provider_fails,
):
    import asyncio
    import logging

    import benchmarks.financial_dependency_suite.application_comparison as app
    import benchmarks.financial_dependency_suite.heldout.run_benchmark as driver
    import benchmarks.financial_dependency_suite.heldout.runner as runner
    from benchmarks.financial_dependency_suite.heldout.loader import application_candidates

    discovered = driver.discover_cases(driver.CASES_DIR)
    first = discovered[0][2]
    assert first.case_id == "analytics_derived_metric_cycle"
    calls = []
    selected_ids = []
    original_selection = runner.run_selection

    async def selection(method, case, **kwargs):
        calls.append((case.case_id, method, kwargs.get("provider")))
        if method == "llm":
            selected_ids[:] = [
                item["source"]
                for item in application_candidates(case)[:case.context_budget]
            ]
            return await original_selection(method, case, **kwargs)
        result = {
            "selected": application_candidates(case)[:case.context_budget],
            "latency_seconds": 0.1,
        }
        return {"selection": result, "failure": None} if method == "cohere" else result

    async def fake_provider(*args, **kwargs):
        if provider_fails:
            raise RuntimeError("mock provider unavailable")
        return {
            "text": json.dumps({"selected_sources": selected_ids}),
            "provider": kwargs["provider"], "model": kwargs["model"],
            "latency_seconds": 0.1, "input_tokens": 10, "output_tokens": 2,
        }

    async def answer(*args, **kwargs):
        return {"generation": {"text": "mock answer", "latency_seconds": 0.2},
                "failure": None}

    monkeypatch.setattr(driver, "warm_local_models", lambda *args: None)
    monkeypatch.setattr(runner, "run_selection", selection)
    monkeypatch.setattr(app, "generate", fake_provider)
    monkeypatch.setattr(runner, "generate_answer_safe", answer)
    caplog.set_level(logging.INFO)
    run_dir = asyncio.run(driver.run_benchmark(results_dir=tmp_path, trials=1))
    records = [json.loads(line) for line in (run_dir / "results.jsonl").read_text().splitlines()]
    assert calls[3] == (first.case_id, "llm", "anthropic")
    assert len(records) == len(discovered) * len(driver.METHODS)
    assert records[3]["method"] == "anthropic"
    if provider_fails:
        assert records[3]["answer_score"] == "selection_failure"
        assert records[3]["failure_type"] == "provider_error"
    else:
        assert records[3]["selected"]
        assert "failure_type" not in records[3]
    assert records[-1]["method"] == "omneum"
    summary = json.loads((run_dir / "summary.json").read_text())
    assert summary["anthropic"]["failures"] == (len(discovered) if provider_fails else 0)
    assert "Starting case_id=analytics_derived_metric_cycle method=anthropic trial=1" in caplog.text
    if provider_fails:
        assert "Failed case_id=analytics_derived_metric_cycle method=anthropic trial=1" in caplog.text
        assert "mock provider unavailable" in caplog.text
