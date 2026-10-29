
import asyncio
import json
from copy import deepcopy

import pytest

from omneum.context_selection import token_count
from research.archive.context_optimization import run as experiment


@pytest.fixture
def cases():
    return experiment.discover_cases(experiment.CASES_DIR)


@pytest.fixture
def semantic(monkeypatch):

    calls = []

    def rank(question, candidates, *, top_n):

        calls.append((
            question,
            deepcopy(candidates),
            top_n,
        ))

        selected = []

        # reverse the candidates so the test can detect changes in ranking order
        for index, candidate in reversed(list(enumerate(candidates))):

            selected.append({
                **candidate,
                "reranker_score": float(index),
            })

        return {
            "selected": selected,
            "model": "fixture",
            "latency_seconds": 0.01,
        }

    monkeypatch.setattr(experiment, "select_bge", rank)

    return calls


@pytest.mark.parametrize("budget", [0, 40, 100])
def test_shared_pool_and_budget(cases, semantic, monkeypatch, budget):

    evaluated = []
    evaluate = experiment.evaluate_context

    def track(observations, *, estimator):

        evaluated.append(observations)

        # the evaluator receives structured observations, never raw chunk text
        assert all(
            not hasattr(item, "raw_text")
            for item in observations
        )

        return evaluate(
            observations,
            estimator=estimator,
        )

    monkeypatch.setattr(experiment, "evaluate_context", track)

    for _, _, case, _ in cases:

        before = deepcopy(case)
        selections = {}

        # all four methods must select from the same unchanged candidate pool
        for method in experiment.METHODS:

            selections[method] = experiment.select_context(
                method,
                case,
                budget,
            )

        assert case == before

        expected_observations, _ = experiment.build_observations(case)

        assert evaluated[-1] == evaluated[-2] == expected_observations

        assert semantic[-1] == semantic[-2]
        assert semantic[-1][1] == experiment.application_candidates(case)
        assert semantic[-1][2] == len(case.candidates)

        candidate_ids = {
            candidate.source_id
            for candidate in case.candidates
        }

        # selected text must fit the budget and come from the original candidates
        for selection in selections.values():

            assert (
                selection["context_units"]
                == token_count(selection["context"])
                <= budget
            )

            assert set(selection["selected_chunk_ids"]) <= candidate_ids

            json.dumps(selection)


def test_generation_and_artifacts(cases, semantic, monkeypatch, tmp_path):

    _, _, case, _ = cases[0]

    calls = []

    async def generate(question, documents, *, provider, model):

        calls.append((
            question,
            deepcopy(documents),
            provider,
            model,
        ))

        return {
            "generation": {
                "text": "fixture answer",
                "input_tokens": 23,
                "output_tokens": 4,
                "latency_seconds": 0.02,
            },
            "failure": None,
        }

    monkeypatch.setattr(
        experiment,
        "generate_answer_safe",
        generate,
    )

    output = tmp_path / "run"

    asyncio.run(
        experiment.run(
            output,
            model="fixture",
            limit=1,
            trials=2,
            budget=60,
        )
    )

    records = [
        json.loads(line)
        for line in (output / "results.jsonl").read_text().splitlines()
    ]

    metadata = json.loads(
        (output / "manifest.json").read_text()
    )

    summary = json.loads(
        (output / "summary.json").read_text()
    )

    assert len(records) == len(calls) == 8

    # the second trial starts with the next method in the rotation
    expected_order = list(
        experiment.METHODS[1:] + experiment.METHODS[:1]
    )

    assert [
        record["method"]
        for record in records[4:]
    ] == expected_order

    assert metadata["case_ids"] == [case.case_id]
    assert len(metadata["inputs"]) == 2
    assert len(metadata["experiment_sha256"]) == 64

    # generator inputs must match the evidence recorded for each method
    for record, call in zip(records, calls, strict=True):

        question, documents, provider, model = call

        assert question == case.question
        assert (provider, model) == ("anthropic", "fixture")

        assert [
            document["source"]
            for document in documents
        ] == record["selected"]

        assert (
            record["selection"]["context_units"]
            == token_count(record["generator_context"])
            <= 60
        )

        assert (
            record["end_to_end_latency_seconds"]
            >= record["selection"]["latency_seconds"]
        )

    for metrics in summary.values():

        assert metrics["attempted"] == 2

        assert (
            metrics["generator_usage"]["input_tokens"]["sum"]
            == 46
        )

        assert metrics["proxy_metrics"]["context_units"] <= 60

    # existing output directories must not be overwritten
    with pytest.raises(FileExistsError):

        asyncio.run(
            experiment.run(
                output,
                model="fixture",
                limit=1,
            )
        )


def test_failures_are_not_successes(cases, monkeypatch):

    _, _, case, truth = cases[0]

    def fail(*args, **kwargs):
        raise RuntimeError("private provider body")

    monkeypatch.setattr(experiment, "select_bge", fail)

    async def fail_generation(*args, **kwargs):

        return {
            "generation": None,
            "failure": {
                "answer": None,
                "answer_score": "generation_failure",
                "failure_type": "provider_error",
            },
        }

    monkeypatch.setattr(
        experiment,
        "generate_answer_safe",
        fail_generation,
    )

    records = asyncio.run(
        experiment.run_case(
            case,
            truth,
            budget=100,
            provider="fixture",
            model="fixture",
            trial=1,
        )
    )

    assert len(records) == 4

    assert [
        record["answer_score"]
        for record in records
    ] == [
        "generation_failure",
        "selection_failure",
        "generation_failure",
        "selection_failure",
    ]

    summary = experiment.aggregate(records)

    for metrics in summary.values():
        assert metrics["accuracy"] == 0

    # provider exception text must not leak into saved records
    assert "private provider body" not in json.dumps(records)


def test_redundancy_and_combination(cases, semantic):

    case = next(
        case
        for _, _, case, _ in cases
        if case.case_id == "enterprise_policy_copy_chain"
    )

    retrieval = experiment.select_context(
        "retrieval",
        case,
        10_000,
    )

    combined = experiment.select_context(
        "semantic_omneum",
        case,
        10_000,
    )

    omneum = experiment.select_context(
        "omneum",
        case,
        10_000,
    )

    assert retrieval["repeated_claim_fraction"] > 0

    assert (
        combined["repeated_claim_fraction"]
        == omneum["repeated_claim_fraction"]
        == 0
    )

    assert (
        combined["evaluation"]["claim_support"]
        == omneum["evaluation"]["claim_support"]
    )

    assert (
        set(combined["covered_claim_ids"])
        == set(omneum["covered_claim_ids"])
    )


@pytest.mark.parametrize(
    "options",
    [
        {"budget": -1},
        {"trials": 0},
        {"limit": 0},
        {"case_ids": ["missing"]},
    ],
)
def test_invalid_configuration(tmp_path, options):

    output = tmp_path / "invalid"

    with pytest.raises(ValueError):

        asyncio.run(
            experiment.run(
                output,
                model="fixture",
                **options,
            )
        )

    assert not output.exists()
