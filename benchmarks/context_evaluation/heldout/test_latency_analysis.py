"""Offline analysis contracts; no provider calls or historical artifact writes."""

from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest


# Load the standalone script without invoking heldout's SDK adapter initializer.
SCRIPT = Path(__file__).with_name("latency_analysis.py")
spec = importlib.util.spec_from_file_location("latency_analysis", SCRIPT)
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


def pair(*, cached_method="cohere_omneum"):
    rows = []
    for method in analysis.METHODS:
        hit = method == cached_method
        work = 0.0 if hit else 2.0
        omneum = .5 if method == "cohere_omneum" else 0
        selection = {"cohere_request_hash": "shared", "cohere_cache_hit": hit,
                     "cohere_response_latency_seconds": 2., "cohere_latency_seconds": work,
                     "latency_seconds": work + omneum,
                     "relevance_model": "model", "relevance_depth": 1,
                     "relevance_selected": [{"source": "s"}]}
        if omneum:
            selection.update(omneum_latency_seconds=omneum,
                             cold_integration_latency_seconds=omneum,
                             evaluation_latency_seconds=.1)
        rows.append({"method": method, "case_id": "case", "trial": 1,
                     "selection": selection, "generation": {"latency_seconds": 3.},
                     "end_to_end_latency_seconds": work + omneum + 3})
    return rows


@pytest.mark.parametrize("cached_method", ["cohere", "cohere_omneum", None])
def test_cache_replacement_once_and_nested_evaluation(cached_method):
    report = analysis.analyze(pair(cached_method=cached_method), expected_cases=1)
    metrics = report["metrics"]
    assert metrics["cohere"]["corrected_end_to_end"]["p50"] == 5
    assert metrics["cohere_omneum"]["corrected_end_to_end"]["p50"] == 5.5
    assert metrics["cohere_omneum"]["cold_overhead"]["p50"] == pytest.approx(.4)
    assert report["warnings"] == []


def test_percentiles_are_computed_from_case_totals():
    rows = pair()
    second = deepcopy(rows)
    for row in second:
        row["case_id"] = "other"
        row["selection"]["cohere_request_hash"] = "other"
        # High reranking and low generation in the first case, reversed here.
        row["selection"]["cohere_response_latency_seconds"] = 1
        row["generation"]["latency_seconds"] = 9
        if row["method"] == "cohere":
            row["selection"]["cohere_latency_seconds"] = 1
            row["selection"]["latency_seconds"] = 1
        row["end_to_end_latency_seconds"] = row["selection"]["latency_seconds"] + 9
    report = analysis.analyze(rows + second, expected_cases=2)
    assert report["metrics"]["cohere"]["corrected_end_to_end"]["p95"] == pytest.approx(9.75)
    assert analysis.percentile([0, 10, 20, 30], .95) == pytest.approx(28.5)


@pytest.mark.parametrize("change", ["duplicate", "missing_pair", "hash", "response", "file", "scores"])
def test_incompatible_pairs_rejected(change):
    rows = pair()
    responses = []
    if change == "duplicate":
        rows.append(deepcopy(rows[0]))
    elif change == "missing_pair":
        rows.pop()
    elif change == "hash":
        rows[1]["selection"]["cohere_request_hash"] = "different"
    elif change == "response":
        rows[1]["selection"]["cohere_response_latency_seconds"] = 0
    elif change == "scores":
        rows[1]["selection"]["relevance_selected"] = []
    else:
        responses = [{"request_hash": "shared", "selection": {"latency_seconds": 1}}]
    with pytest.raises(ValueError):
        analysis.analyze(rows, responses, expected_cases=1)


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), -1, True, .6])
def test_missing_latency_components(bad):
    rows = pair()
    rows[1]["selection"]["evaluation_latency_seconds"] = bad
    report = analysis.analyze(rows, expected_cases=1)
    assert report["metrics"]["cohere_omneum"]["cold_overhead"]["n"] == 0
    assert report["metrics"]["cohere_omneum"]["corrected_end_to_end"]["p50"] == 5.5
    assert report["warnings"]


@pytest.mark.parametrize("field", ["cohere_latency_seconds", "latency_seconds", "cold_integration_latency_seconds"])
def test_inconsistent_latency_components(field):
    rows = pair()
    rows[1]["selection"][field] = 9
    report = analysis.analyze(rows, expected_cases=1)
    assert report["metrics"]["cohere_omneum"]["corrected_end_to_end"]["n"] == 0
    assert report["warnings"]


def test_recorded_end_to_end_mismatch_is_not_silently_replaced():
    rows = pair()
    rows[1]["end_to_end_latency_seconds"] = 99
    report = analysis.analyze(rows, expected_cases=1)
    assert report["metrics"]["cohere_omneum"]["corrected_end_to_end"]["n"] == 0
    assert report["warnings"]


def test_historical_run_read_only_offline_and_expected_values():
    directory = analysis.DEFAULT_RESULTS.parent
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir() if p.is_file()}
    # -S removes site packages: the CLI cannot import paid provider SDKs.
    process = subprocess.run([sys.executable, "-S", str(SCRIPT)], capture_output=True, text=True, check=True)
    assert "E2E corrected [reconstructed]" in process.stdout
    report = analysis.analyze(analysis.read_jsonl(analysis.DEFAULT_RESULTS),
                              analysis.read_jsonl(directory / "cohere_responses.jsonl"))
    assert report["paired_cases"] == 24
    assert report["shared_response_file_verified"]
    assert report["warnings"] == []
    assert sum(s["cache_hit"] for s in report["samples"]["cohere_omneum"]) == 24
    assert report["metrics"]["cohere"]["reranking"]["p95"] == pytest.approx(2.901376101642377)
    assert report["metrics"]["cohere"]["corrected_end_to_end"]["p50"] == pytest.approx(2.634260832797736)
    corrected = report["metrics"]["cohere_omneum"]["corrected_end_to_end"]
    assert corrected["p50"] == pytest.approx(3.1765, abs=.00005)
    assert corrected["p95"] == pytest.approx(6.0220, abs=.00005)
    after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir() if p.is_file()}
    assert before == after
