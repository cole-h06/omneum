from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import verity.inference as inference_module
from verity.engine_graph import (
    AssertionTriple,
    PairValues,
    SourcePair,
    build_graph,
)
from verity.inference import (
    CONVERGENCE_TOLERANCE,
    InferenceError,
    infer,
)


VECTOR_PATH = (
    Path(__file__).parent
    / "vectors"
    / "inference_v1.json"
)


def graph(assertions, dependencies=None, coverage=None):
    source_ids = sorted({item.source_id for item in assertions})
    dependencies = dependencies or {}
    coverage = coverage or {}
    pairs = [
        SourcePair(
            source_a_id,
            source_b_id,
            dependencies.get((source_a_id, source_b_id), 0.0),
            coverage.get((source_a_id, source_b_id), 0.0),
        )
        for index, source_a_id in enumerate(source_ids)
        for source_b_id in source_ids[index + 1:]
    ]
    return build_graph(assertions, pairs)


def claim(result, claim_id):
    return next(
        item
        for item in result.claim_support
        if item.claim_id == claim_id
    )


def test_single():
    result = infer(graph([
        AssertionTriple("source-a", "attribute-a", "claim-a"),
    ]))

    assert result.summary.source_count == 1
    assert result.summary.claim_count == 1
    assert result.summary.assertion_count == 1
    assert result.source_credibility[0].credibility == 1.0
    assert result.claim_support[0].support == 1.0
    assert result.claim_support[0].agreement_weight == 1.0
    assert result.claim_support[0].supporting_source_count == 1
    assert (
        result.claim_support[0].estimated_independent_support_count
        == 1.0
    )
    assert result.claim_support[0].dependency_confidence is None
    assert result.metadata.iterations == 1
    assert result.metadata.maximum_credibility_delta == 0.0


def test_agreement():
    result = infer(graph([
        AssertionTriple("source-a", "attribute-a", "claim-a"),
        AssertionTriple("source-b", "attribute-a", "claim-a"),
        AssertionTriple("source-c", "attribute-a", "claim-b"),
    ]))

    assert claim(result, "claim-a").agreement_weight == 2 / 3
    assert claim(result, "claim-b").agreement_weight == 1 / 3


def test_dependency():
    assertions = [
        AssertionTriple("source-a", "attribute-a", "claim-a"),
        AssertionTriple("source-b", "attribute-a", "claim-a"),
    ]
    independent = infer(graph(assertions))
    dependent = infer(graph(
        assertions,
        {("source-a", "source-b"): 0.5},
    ))

    assert claim(independent, "claim-a").support == 1.0
    assert claim(dependent, "claim-a").support == 0.5
    assert (
        claim(dependent, "claim-a")
        .estimated_independent_support_count
        == 4 / 3
    )


def test_independence():
    result = infer(graph(
        [
            AssertionTriple("source-a", "attribute-a", "claim-a"),
            AssertionTriple("source-b", "attribute-a", "claim-a"),
            AssertionTriple("source-c", "attribute-b", "claim-b"),
        ],
        {("source-a", "source-b"): 0.25},
    ))

    shared = claim(result, "claim-a")
    singleton = claim(result, "claim-b")
    assert {
        item.source_id: item.independence
        for item in shared.supporting_sources
    } == {"source-a": 0.75, "source-b": 0.75}
    assert singleton.supporting_sources[0].independence == 1.0


def test_confidence():
    result = infer(graph(
        [
            AssertionTriple("source-a", "attribute-a", "claim-a"),
            AssertionTriple("source-b", "attribute-a", "claim-a"),
            AssertionTriple("source-c", "attribute-a", "claim-a"),
        ],
        coverage={
            ("source-a", "source-b"): 0.25,
            ("source-a", "source-c"): 0.5,
            ("source-b", "source-c"): 1.0,
        },
    ))

    assert claim(result, "claim-a").dependency_confidence == (
        1.75 / 3
    )


def test_ties():
    result = infer(graph([
        AssertionTriple("source-a", "attribute-a", "claim-a"),
        AssertionTriple("source-b", "attribute-a", "claim-b"),
    ]))

    assert all(item.is_attribute_max_support for item in result.claim_support)
    assert result.claim_support[0].conflicting_claims[0].claim_id == "claim-b"
    assert result.claim_support[1].conflicting_claims[0].claim_id == "claim-a"


def test_contributions():
    result = infer(graph([
        AssertionTriple("source-a", "attribute-a", "claim-a"),
        AssertionTriple("source-a", "attribute-b", "claim-b"),
        AssertionTriple("source-b", "attribute-a", "claim-a"),
    ]))

    for item in result.claim_support:
        total = sum(
            source.contribution
            for source in item.supporting_sources
        )
        assert total == item.support

        for source in item.supporting_sources:
            credibility = next(
                score.credibility
                for score in result.source_credibility
                if score.source_id == source.source_id
            )
            degree = 2 if source.source_id == "source-a" else 1
            assert source.contribution == (
                credibility
                * item.agreement_weight
                * source.independence
                / degree
            )


def test_ordering():
    result = infer(graph([
        AssertionTriple("source-c", "attribute-b", "claim-c"),
        AssertionTriple("source-b", "attribute-a", "claim-b"),
        AssertionTriple("source-a", "attribute-a", "claim-a"),
        AssertionTriple("source-c", "attribute-a", "claim-a"),
    ]))

    assert list(result.source_credibility) == sorted(
        result.source_credibility,
        key=lambda item: (-item.credibility, item.source_id),
    )
    assert list(result.claim_support) == sorted(
        result.claim_support,
        key=lambda item: (
            item.attribute_id,
            -item.support,
            item.claim_id,
        ),
    )
    for item in result.claim_support:
        assert list(item.supporting_sources) == sorted(
            item.supporting_sources,
            key=lambda source: (
                -source.contribution,
                source.source_id,
            ),
        )
        assert list(item.conflicting_claims) == sorted(
            item.conflicting_claims,
            key=lambda conflict: (
                -conflict.support,
                conflict.claim_id,
            ),
        )


def test_convergence():
    result = infer(graph([
        AssertionTriple("source-a", "attribute-a", "claim-a"),
        AssertionTriple("source-a", "attribute-b", "claim-b"),
        AssertionTriple("source-b", "attribute-a", "claim-a"),
    ]))

    assert result.metadata.iterations < 1000
    assert result.metadata.converged is True
    assert result.metadata.convergence_tolerance == CONVERGENCE_TOLERANCE
    assert result.metadata.maximum_credibility_delta < CONVERGENCE_TOLERANCE


def test_nonconvergence(monkeypatch):
    monkeypatch.setattr(inference_module, "MAX_ITERATIONS", 1)
    value = graph([
        AssertionTriple("source-a", "attribute-a", "claim-a"),
        AssertionTriple("source-a", "attribute-b", "claim-b"),
        AssertionTriple("source-b", "attribute-a", "claim-a"),
    ])

    with pytest.raises(InferenceError):
        infer(value)


def test_zero_total():
    value = graph(
        [
            AssertionTriple("source-a", "attribute-a", "claim-a"),
            AssertionTriple("source-b", "attribute-a", "claim-a"),
        ],
        {("source-a", "source-b"): 1.0},
    )

    with pytest.raises(InferenceError):
        infer(value)


def test_nonfinite():
    value = graph([
        AssertionTriple("source-a", "attribute-a", "claim-a"),
        AssertionTriple("source-b", "attribute-a", "claim-a"),
    ])
    invalid = replace(
        value,
        source_pairs={
            ("source-a", "source-b"): PairValues(
                float("nan"),
                0.0,
            ),
        },
    )

    with pytest.raises(InferenceError):
        infer(invalid)


def load_vector():
    return json.loads(VECTOR_PATH.read_text(encoding="utf-8"))


def vector_result(vector):
    assertions = [
        AssertionTriple(**item)
        for item in vector["assertions"]
    ]
    source_pairs = [
        SourcePair(**item)
        for item in vector["source_pairs"]
    ]
    return json.loads(json.dumps(
        asdict(infer(build_graph(assertions, source_pairs)))
    ))


def test_golden():
    vector = load_vector()

    assert len(vector["assertions"]) == 15
    assert len({
        item["source_id"]
        for item in vector["assertions"]
    }) == 5
    assert vector_result(vector) == vector["result"]


def test_hash_seeds():
    script = (
        "import json, runpy; "
        "module = runpy.run_path('tests/test_inference.py'); "
        "print(json.dumps(module['vector_result'](module['load_vector']()), "
        "sort_keys=True, separators=(',', ':')))"
    )
    outputs = []
    for seed in ("1", "7", "101"):
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = seed
        completed = subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
        outputs.append(completed.stdout)

    assert len(set(outputs)) == 1
