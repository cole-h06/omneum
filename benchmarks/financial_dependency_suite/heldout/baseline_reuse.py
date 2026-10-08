"""Read and validate a prior Anthropic baseline for an additive paired run."""

import hashlib
from dataclasses import asdict
from importlib.metadata import version
import json
import platform
from pathlib import Path
import sys

from benchmarks.financial_dependency_suite.reproducibility import sha256_file
from benchmarks.financial_dependency_suite.config import estimator_config

from .scoring import score_answer, score_selection


def load_anthropic_baseline(results_path, discovered, *, generator_model):
    results_path = Path(results_path).resolve()
    manifest_path = results_path.with_name("manifest.json")
    if not results_path.is_file() or not manifest_path.is_file():
        raise ValueError("baseline results and adjacent manifest are required")
    manifest = json.loads(manifest_path.read_text())
    contract = manifest.get("checkpoint_contract", {})
    if manifest.get("benchmark") != "heldout-context-evaluation" or manifest.get("track") != "application":
        raise ValueError("baseline is not an application heldout run")
    if manifest.get("trials") != 1 or contract.get("trials") != 1:
        raise ValueError("baseline must contain exactly one trial per case")
    if contract.get("generator_provider") != "anthropic":
        raise ValueError("baseline generation provider is not Anthropic")
    models = manifest.get("models", {})
    if models.get("anthropic") != "claude-sonnet-5-5" or models.get("generator") != generator_model:
        raise ValueError("baseline evaluator or generator model differs")
    if manifest.get("estimator") != contract.get("estimator"):
        raise ValueError("baseline estimator manifest and checkpoint contract differ")
    if manifest.get("estimator") != asdict(estimator_config()):
        raise ValueError("baseline Omneum estimator differs from the current estimator configuration")
    anthropic_version = version("anthropic")
    if manifest.get("packages", {}).get("anthropic") != anthropic_version:
        raise ValueError("Anthropic SDK version differs from the baseline")
    current_python = {
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "version": sys.version,
    }
    if manifest.get("python") != current_python:
        raise ValueError("Python runtime differs from the baseline; use its recorded interpreter/platform")

    expected = {}
    for case_path, truth_path, case, _truth in discovered:
        for source in (case_path, truth_path):
            saved = manifest.get("inputs", {}).get(str(Path(source).resolve()))
            actual = sha256_file(source)
            if saved is None or saved != actual:
                raise ValueError(f"baseline input hash mismatch: {source}")
        expected[case.case_id] = (case, _truth)

    records = {}
    for line in results_path.read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("method") != "anthropic":
            continue
        case_id = record.get("case_id")
        if case_id not in expected or record.get("trial") != 1 or case_id in records:
            raise ValueError("baseline Anthropic rows have unexpected or duplicate case/trial identities")
        case, truth = expected[case_id]
        selection = record.get("selection") or {}
        generation = record.get("generation") or {}
        if selection.get("provider") != "anthropic" or selection.get("model") != "claude-sonnet-5-5":
            raise ValueError(f"baseline evaluator model metadata mismatch: {case_id}")
        if generation.get("provider") != "anthropic" or generation.get("model") != generator_model:
            raise ValueError(f"baseline generator metadata mismatch: {case_id}")
        if record.get("domain") != case.domain or len(record.get("selected") or []) != case.context_budget:
            raise ValueError(f"baseline selection budget or case metadata mismatch: {case_id}")
        candidate_ids = {candidate.source_id for candidate in case.candidates}
        if not set(record["selected"]).issubset(candidate_ids):
            raise ValueError(f"baseline selected unknown candidate: {case_id}")
        if (record.get("selection_score") is not None
                and record.get("selection_score") != score_selection(record["selected"], truth)):
            raise ValueError(f"baseline selection score does not match current scoring contract: {case_id}")
        if record.get("answer_score") not in {"correct", "incorrect", "unscored", "generation_failure"}:
            raise ValueError(f"baseline answer score is unavailable: {case_id}")
        if record["answer_score"] != "generation_failure":
            if not isinstance(record.get("answer"), str) or record["answer_score"] != score_answer(record["answer"], truth):
                raise ValueError(f"baseline answer score does not match current scoring contract: {case_id}")
        records[(case_id, "anthropic", 1)] = record

    if set(key[0] for key in records) != set(expected):
        raise ValueError("baseline must provide exactly one Anthropic row for every current case")

    digest = hashlib.sha256()
    digest.update(results_path.read_bytes())
    digest.update(manifest_path.read_bytes())
    return records, {
        "results_path": str(results_path),
        "manifest_path": str(manifest_path),
        "sha256_results_and_manifest": digest.hexdigest(),
        "reused_method": "anthropic",
        "reused_records": len(records),
        "compatibility": {
            "case_and_ground_truth_hashes": "verified",
            "context_budgets": "verified against current cases",
            "evaluator_and_generator_model": "claude-sonnet-5-5 verified",
            "generator_provider": "anthropic verified",
            "python_runtime_and_anthropic_sdk": "exact versions verified",
            "omneum_estimator": "verified against current estimator configuration",
            "scoring_contract": "current heldout scoring applied to the same hash-verified ground truth; baseline scores preserved",
            "generation_parameters": "not serialized in artifact; historical prompt and 1024-token default verified from baseline commit",
        },
    }
