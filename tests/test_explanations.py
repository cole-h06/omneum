import json
from pathlib import Path

import pytest

from verity.client import (
    ClaimSupportResult,
    ConflictingClaimResult,
    SupportingSourceResult,
)
from verity.dependency import (
    DependencyCluster,
    DependencyEvidence,
    DependencySignalScores,
    PairwiseDependencyResult,
)
from verity.explanations import explain_claim, explain_dependency
from verity.information import Claim, Source, SourceReference
from verity.serialization import serialize_source


VECTOR_PATH = Path(__file__).parent / "vectors" / "explanations_v1.json"


def vectors():
    return json.loads(VECTOR_PATH.read_text())


def sources(values):
    return {
        name: Source(item["kind"], item["identifier"])
        for name, item in values["sources"].items()
    }


def claim_result(case, source_values):
    supporting = tuple(
        SupportingSourceResult(source_values[name], 1.0, 0.0)
        for name in case["supporting_sources"]
    )
    conflicts = tuple(
        ConflictingClaimResult(
            Claim(
                "service",
                "enterprise",
                case["attribute"],
                item["value"],
            ),
            float(item["support"]),
        )
        for item in case["conflicts"]
    )
    clusters = None
    if case["clusters"] is not None:
        clusters = tuple(
            DependencyCluster(
                0.4,
                tuple(
                    SourceReference(
                        source_values[name].kind,
                        source_values[name].identifier,
                    )
                    for name in cluster
                ),
            )
            for cluster in case["clusters"]
        )
    return ClaimSupportResult(
        Claim(
            "service",
            "enterprise",
            case["attribute"],
            case["value"],
        ),
        float(case["support"]),
        1.0,
        case["is_attribute_max_support"],
        len(supporting),
        float(case["estimated_independent_support"]),
        (
            None
            if case["dependency_signal_coverage"] is None
            else float(case["dependency_signal_coverage"])
        ),
        supporting,
        conflicts,
        clusters,
    )


def dependency_result(case, source_values):
    signal_values = {}
    for name in (
        "provenance",
        "lineage",
        "ownership",
        "temporal",
        "structural",
    ):
        score, observable = case["signals"].get(name, [0.0, False])
        signal_values[name] = float(score)
        signal_values[f"{name}_observable"] = observable
    signals = DependencySignalScores(**signal_values)
    endpoints = [source_values[name] for name in case["sources"]]
    endpoints.sort(
        key=lambda source: serialize_source(source.kind, source.identifier)
    )
    evidence = case.get("evidence")
    if evidence is not None:
        evidence = DependencyEvidence(
            evidence.get("source_a_cites_source_b", False),
            evidence.get("source_b_cites_source_a", False),
            evidence.get("source_a_parent_count", 0),
            evidence.get("source_b_parent_count", 0),
            evidence.get("same_owner", False),
            evidence.get("shared_provenance_count", 0),
            evidence.get("matching_claim_count", 0),
            tuple(float(value) for value in evidence.get("time_deltas", [])),
        )
    return PairwiseDependencyResult(
        SourceReference(endpoints[0].kind, endpoints[0].identifier),
        SourceReference(endpoints[1].kind, endpoints[1].identifier),
        signals,
        float(case["dependency"]),
        float(case["weighted_signal_coverage"]),
        evidence,
    )


def test_claim_vectors():
    values = vectors()
    source_values = sources(values)
    for case in values["claim_cases"]:
        result = claim_result(case, source_values)
        assert explain_claim(result) == case["expected"]
        assert explain_claim(result) == explain_claim(result)
        assert not explain_claim(result).endswith("\n")


def test_dependency_vectors():
    values = vectors()
    source_values = sources(values)
    for case in values["dependency_cases"]:
        result = dependency_result(case, source_values)
        labels = {
            source_values[name]: label
            for name, label in case.get("labels", {}).items()
        }
        assert explain_dependency(
            result,
            source_labels=labels or None,
        ) == case["expected"]
        assert explain_dependency(
            result,
            source_labels=labels or None,
        ) == explain_dependency(result, source_labels=labels or None)
        assert not case["expected"].endswith("\n")


@pytest.mark.parametrize(
    "labels",
    [
        {Source("web_publisher", "a.example"): ""},
        {Source("web_publisher", "a.example"): "bad\nlabel"},
        {Source("web_publisher", "a.example"): 1},
        {"a.example": "Label"},
        [],
    ],
)
def test_labels(labels):
    values = vectors()
    result = dependency_result(values["dependency_cases"][0], sources(values))
    with pytest.raises((TypeError, ValueError)) as caught:
        explain_dependency(result, source_labels=labels)
    assert "bad" not in str(caught.value)
    assert "a.example" not in repr(caught.value)


def test_equivalent_labels():
    values = vectors()
    result = dependency_result(values["dependency_cases"][0], sources(values))
    labels = {
        Source("web_publisher", "HTTPS://EXAMPLE.COM/"): "First",
        Source("web_publisher", "example.com"): "Second",
    }
    with pytest.raises(ValueError, match="duplicate sources"):
        explain_dependency(result, source_labels=labels)


def test_label_source_error():
    values = vectors()
    result = dependency_result(values["dependency_cases"][0], sources(values))
    labels = {
        Source("internal_resource", "secret-marker"): "Safe label",
    }
    with pytest.raises(ValueError) as caught:
        explain_dependency(result, source_labels=labels)
    assert "secret-marker" not in str(caught.value)
    assert "secret-marker" not in repr(caught.value)


def test_exact_inputs():
    with pytest.raises(TypeError):
        explain_claim({})
    with pytest.raises(TypeError):
        explain_dependency({})


def test_prohibited_words():
    values = vectors()
    source_values = sources(values)
    output = "\n".join(
        [
            *(explain_claim(claim_result(case, source_values))
              for case in values["claim_cases"]),
            *(explain_dependency(dependency_result(case, source_values))
              for case in values["dependency_cases"]),
        ]
    ).lower()
    for phrase in (
        "truth probability",
        "correctness probability",
        "materially reduced",
        "primarily dependent",
        "strongly independent",
        "copied",
        "coordinated",
        "⚠",
    ):
        assert phrase not in output


def test_internal_redaction():
    values = vectors()
    source_values = sources(values)
    case = next(
        item
        for item in values["dependency_cases"]
        if item["name"] == "internal_fallback"
    )
    output = explain_dependency(dependency_result(case, source_values))
    assert source_values["sql"].identifier not in output
    assert "12345678" not in output
