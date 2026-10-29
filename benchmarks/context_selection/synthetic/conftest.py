"""Synthetic baseline records for offline reuse-contract tests."""
from dataclasses import asdict
from importlib.metadata import version
import hashlib
import json
import platform
import sys

import pytest

from benchmarks.context_selection.config import estimator_config
from .run_benchmark import CASES_DIR, discover_cases
from .scoring import score_answer, score_selection


@pytest.fixture
def baseline_results(tmp_path):
    directory = tmp_path / "synthetic-baseline"
    directory.mkdir()
    inputs, rows = {}, []
    for case_path, truth_path, case, truth in discover_cases(CASES_DIR):
        for path in (case_path, truth_path):
            inputs[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        selected = [candidate.source_id for candidate in case.candidates[:case.context_budget]]
        rows.append({
            "case_id": case.case_id, "domain": case.domain, "trial": 1,
            "method": "anthropic", "selected": selected, "answer": truth.answer,
            "selection_score": score_selection(selected, truth),
            "answer_score": score_answer(truth.answer, truth),
            "selection": {"provider": "anthropic", "model": "claude-sonnet-5-5"},
            "generation": {"provider": "anthropic", "model": "claude-sonnet-5-5"},
        })
    estimator = asdict(estimator_config())
    manifest = {
        "benchmark": "heldout-context-evaluation", "track": "application",
        "trials": 1, "models": {"anthropic": "claude-sonnet-5-5", "generator": "claude-sonnet-5-5"},
        "estimator": estimator, "packages": {"anthropic": version("anthropic")},
        "python": {"implementation": platform.python_implementation(),
                   "platform": platform.platform(), "version": sys.version},
        "inputs": inputs,
        "checkpoint_contract": {"trials": 1, "generator_provider": "anthropic", "estimator": estimator},
    }
    (directory / "manifest.json").write_text(json.dumps(manifest))
    results = directory / "results.jsonl"
    results.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return results
