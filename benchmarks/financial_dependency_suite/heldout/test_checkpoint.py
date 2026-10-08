import asyncio
import json

import pytest

from . import artifacts, suite
from . import run_benchmark as driver
from .checkpoint import TrialCheckpoint
from .methods import MethodSpec


def setup_driver(monkeypatch):
    discovered = driver.discover_cases(driver.CASES_DIR)[:1]
    monkeypatch.setattr(driver, "discover_cases", lambda path: discovered)
    monkeypatch.setattr(driver, "warm_local_models", lambda *args: None)
    monkeypatch.setattr(driver, "implementation_hash", lambda: "offline-code-fingerprint")
    monkeypatch.setattr(driver, "METHODS", (
        MethodSpec(name="vector", method="vector"),
        MethodSpec(name="google", method="llm", provider="google", model="fixture", stochastic=True),
    ))
    return discovered


def test_interruption_and_resume_keep_committed_failures(monkeypatch, tmp_path):
    setup_driver(monkeypatch)
    path = tmp_path / "offline-smoke" / "results.jsonl"
    calls = []

    async def interrupted(method, case, truth, **kwargs):
        # Every previous completed trial is already visible before the next call.
        assert len(path.read_text().splitlines()) == len(calls)
        calls.append(method)
        if len(calls) == 3:
            raise KeyboardInterrupt()
        return {"answer_score": "selection_failure", "failure_type": "provider_error",
                "error": "request failed", "selected": [], "answer": None,
                "selection": {"provider": kwargs["provider"], "model": kwargs["model"]}}

    monkeypatch.setattr(suite, "run_method", interrupted)
    with pytest.raises(KeyboardInterrupt):
        asyncio.run(driver.run_benchmark(results_dir=tmp_path, identifier="offline-smoke", trials=2))
    saved = path.read_bytes()
    assert len(saved.splitlines()) == 2
    assert not (path.parent / "summary.json").exists()
    assert (path.parent / "manifest.json").exists()
    resumed_calls = []

    async def finish(method, case, truth, **kwargs):
        resumed_calls.append(method)
        return {"answer_score": "correct", "answer": "612", "selected": []}

    monkeypatch.setattr(suite, "run_method", finish)
    asyncio.run(driver.run_benchmark(resume=path.parent, trials=2))
    assert resumed_calls == ["llm", "llm"]
    assert path.read_bytes().startswith(saved)
    resumed_records = [json.loads(line) for line in path.read_text().splitlines()]
    assert [(record["method"], record["trial"]) for record in resumed_records] == [
        ("vector", 1), ("vector", 2), ("google", 1), ("google", 2),
    ]
    assert len({(record["case_id"], record["method"], record["trial"]) for record in resumed_records}) == 4
    summary = json.loads((path.parent / "summary.json").read_text())
    assert summary["vector"]["failures"] == 2
    assert summary["google"]["correct"] == 2
    # Resuming a finished run makes no selection/generation calls.
    asyncio.run(driver.run_benchmark(resume=path.parent, trials=2))
    assert resumed_calls == ["llm", "llm"]


def test_resume_rejects_changed_contract_before_work(monkeypatch, tmp_path):
    setup_driver(monkeypatch)

    async def finish(*args, **kwargs):
        return {"answer_score": "correct"}

    monkeypatch.setattr(suite, "run_method", finish)
    directory = asyncio.run(driver.run_benchmark(results_dir=tmp_path, identifier="run", trials=1))
    before = (directory / "results.jsonl").read_bytes()
    monkeypatch.setattr(driver, "warm_local_models", lambda *args: pytest.fail("must not warm models"))
    with pytest.raises(ValueError, match="contract mismatch"):
        asyncio.run(driver.run_benchmark(resume=directory, trials=2))
    monkeypatch.setattr(driver, "implementation_hash", lambda: "changed-code")
    with pytest.raises(ValueError, match="contract mismatch"):
        asyncio.run(driver.run_benchmark(resume=directory, trials=1))
    assert (directory / "results.jsonl").read_bytes() == before


def test_failed_checkpoint_write_preserves_previous_valid_file(monkeypatch, tmp_path):
    path = tmp_path / "results.jsonl"
    artifacts.checkpoint(path, [{"trial": 1}])
    before = path.read_bytes()

    def interrupt(*args):
        raise KeyboardInterrupt()

    monkeypatch.setattr(artifacts.os, "replace", interrupt)
    with pytest.raises(KeyboardInterrupt):
        artifacts.checkpoint(path, [{"trial": 1}, {"trial": 2}])
    assert path.read_bytes() == before
    assert json.loads(path.read_text()) == {"trial": 1}
    assert list(tmp_path.glob(".results-*")) == []


@pytest.mark.parametrize("records", [
    [{"case_id": "wrong", "method": "vector", "trial": 1, "answer_score": "correct"}],
    [{"case_id": "case", "method": "vector", "trial": 1, "answer_score": "invalid"}],
])
def test_resume_rejects_invalid_records(tmp_path, records):
    (tmp_path / "manifest.json").write_text(json.dumps({"checkpoint_contract": {"version": 1}}))
    artifacts.checkpoint(tmp_path / "results.jsonl", records)
    with pytest.raises(ValueError):
        with TrialCheckpoint(tmp_path, {"version": 1}, [("case", "vector", 1)], resume=True):
            pytest.fail("invalid resume must not proceed")


def test_no_overwrite_or_concurrent_resume(tmp_path):
    directory = tmp_path / "run"
    with TrialCheckpoint(directory, {}, []) as progress:
        (directory / "manifest.json").write_text('{"checkpoint_contract": {}}')
        with pytest.raises(BlockingIOError):
            with TrialCheckpoint(directory, {}, [], resume=True):
                pytest.fail("concurrent writer")
        with pytest.raises(FileExistsError):
            with TrialCheckpoint(directory, {}, []):
                pytest.fail("overwritten run")
    assert progress.records == []
