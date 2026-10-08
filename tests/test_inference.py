from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import omneum.inference as inference_module
from omneum.engine_graph import (
    AssertionTriple,
    PairValues,
    SourcePair,
    build_graph,
)
from omneum.inference import (
    CONVERGENCE_TOLERANCE,
    InferenceError,
    infer,
)


VECTOR_PATH = (
    Path(__file__).parent
    / "vectors"
    / "reliability_v2.json"
)


def graph(assertions, dependencies=None, coverage=None, exact_equivalence=None):
    source_ids = sorted({item.source_id for item in assertions})
    dependencies = dependencies or {}
    coverage = coverage or {}
    exact_equivalence = exact_equivalence or set()
    pairs = [
        SourcePair(
            source_a_id,
            source_b_id,
            dependencies.get((source_a_id, source_b_id), 0.0),
            coverage.get((source_a_id, source_b_id), 0.0),
            (source_a_id, source_b_id) in exact_equivalence,
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
    assert result.source_reliability[0].reliability == 1.0
    assert result.claim_support[0].support == 1.0
    assert result.claim_support[0].agreement_weight == 1.0
    assert result.claim_support[0].supporting_source_count == 1
    assert (
        result.claim_support[0].estimated_independent_support_count
        == 1.0
    )
    assert result.claim_support[0].dependency_signal_coverage is None
    assert result.metadata.iterations == 1
    assert result.metadata.convergence_delta == 0.0


def test_agreement():
    result = infer(graph([
        AssertionTriple("source-a", "attribute-a", "claim-a"),
        AssertionTriple("source-b", "attribute-a", "claim-a"),
        AssertionTriple("source-c", "attribute-a", "claim-b"),
    ]))

    assert claim(result, "claim-a").agreement_weight == 2 / 3
    assert claim(result, "claim-b").agreement_weight == 1 / 3



def test_singleton_attributes_do_not_collapse_sources():
    result = infer(graph([
        AssertionTriple("source-a", "attribute-a", "claim-a"),
        AssertionTriple("source-b", "attribute-b", "claim-b"),
        AssertionTriple("source-c", "attribute-c", "claim-c"),
        AssertionTriple("source-d", "attribute-d", "claim-d"),
    ]))

    reliabilities = {
        item.source_id: item.reliability
        for item in result.source_reliability
    }

    assert all(value > 0.0 for value in reliabilities.values())
    assert len(set(reliabilities.values())) == 1


def test_conflicts_differentiate_source_reliability():
    result = infer(graph([
        AssertionTriple("source-a", "attribute-a", "claim-a1"),
        AssertionTriple("source-b", "attribute-a", "claim-a1"),
        AssertionTriple("source-c", "attribute-a", "claim-a2"),

        AssertionTriple("source-a", "attribute-b", "claim-b1"),
        AssertionTriple("source-b", "attribute-b", "claim-b1"),
        AssertionTriple("source-c", "attribute-b", "claim-b2"),

        AssertionTriple("source-a", "attribute-c", "claim-c1"),
        AssertionTriple("source-b", "attribute-c", "claim-c1"),
        AssertionTriple("source-d", "attribute-c", "claim-c2"),
    ]))

    reliabilities = {
        item.source_id: item.reliability
        for item in result.source_reliability
    }

    assert reliabilities["source-a"] == reliabilities["source-b"]
    assert reliabilities["source-a"] > reliabilities["source-c"]
    assert reliabilities["source-b"] > reliabilities["source-d"]


def test_conflict_reliability():
    result = infer(graph([
        AssertionTriple("source-a", "attribute-a", "claim-a1"),
        AssertionTriple("source-b", "attribute-a", "claim-a1"),
        AssertionTriple("source-c", "attribute-a", "claim-a1"),
        AssertionTriple("source-d", "attribute-a", "claim-a2"),

        AssertionTriple("source-a", "attribute-b", "claim-b1"),
        AssertionTriple("source-b", "attribute-b", "claim-b1"),
        AssertionTriple("source-c", "attribute-b", "claim-b1"),
        AssertionTriple("source-d", "attribute-b", "claim-b2"),

        AssertionTriple("source-a", "attribute-c", "claim-c1"),
        AssertionTriple("source-b", "attribute-c", "claim-c1"),
        AssertionTriple("source-c", "attribute-c", "claim-c1"),
        AssertionTriple("source-d", "attribute-c", "claim-c2"),
    ]))

    reliabilities = {
        item.source_id: item.reliability
        for item in result.source_reliability
    }

    assert reliabilities["source-a"] > reliabilities["source-d"]
    assert reliabilities["source-b"] > reliabilities["source-d"]
    assert reliabilities["source-c"] > reliabilities["source-d"]

    prior = 1.0 / 4
    assert reliabilities["source-d"] >= (
        (1.0 - inference_module.PROPAGATION_WEIGHT) * prior
    )

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
    assert claim(dependent, "claim-a").support == pytest.approx(2.0 / 3.0)
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
    } == {"source-a": 0.8, "source-b": 0.8}
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

    assert claim(result, "claim-a").dependency_signal_coverage == (
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
            reliability = next(
                score.reliability
                for score in result.source_reliability
                if score.source_id == source.source_id
            )
            degree = 2 if source.source_id == "source-a" else 1
            assert source.contribution == (
                reliability
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

    assert list(result.source_reliability) == sorted(
        result.source_reliability,
        key=lambda item: (-item.reliability, item.source_id),
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
    assert result.metadata.convergence_delta < CONVERGENCE_TOLERANCE


def test_nonconvergence(monkeypatch):
    monkeypatch.setattr(inference_module, "MAX_ITERATIONS", 1)
    value = graph([
        AssertionTriple("source-a", "attribute-a", "claim-a"),
        AssertionTriple("source-a", "attribute-b", "claim-b"),
        AssertionTriple("source-b", "attribute-a", "claim-a"),
    ])

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


@pytest.mark.parametrize("scenario", ["vector", "exact_equivalence"])
def test_hash_seeds(scenario):
    expression = (
        "module['vector_result'](module['load_vector']())"
        if scenario == "vector" else
        "module['asdict'](module['infer'](module['exact_equivalence_graph'](6, 0.5)))"
    )
    script = (
        "import json, runpy; "
        "module = runpy.run_path('tests/test_inference.py'); "
        f"print(json.dumps({expression}, "
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


def test_dependent_group():
    assertions = [
        AssertionTriple(source, "attribute-a", "claim-a")
        for source in ("source-a", "source-b", "source-c", "source-d")
    ]
    pairs = {
        (a, b): 1.0
        for i, a in enumerate(("source-a", "source-b", "source-c", "source-d"))
        for b in ("source-a", "source-b", "source-c", "source-d")[i + 1:]
    }

    result = infer(graph(assertions, pairs))
    shared = claim(result, "claim-a")

    assert sum(
        item.independence
        for item in shared.supporting_sources
    ) == pytest.approx(1.0)


def test_dependent_copies_do_not_change_claim_ranking():
    def result(copies):
        assertions = [
            AssertionTriple("independent", "attribute", "claim-b"),
            *[
                AssertionTriple(f"copy-{i}", "attribute", "claim-a")
                for i in range(copies)
            ],
        ]
        source_ids = sorted({item.source_id for item in assertions})
        copied = {f"copy-{i}" for i in range(copies)}
        dependencies = {
            (source_a, source_b): 1.0
            for index, source_a in enumerate(source_ids)
            for source_b in source_ids[index + 1:]
            if source_a in copied and source_b in copied
        }
        return infer(graph(assertions, dependencies))

    single = result(1)
    copied = result(10)

    assert claim(single, "claim-a").support == pytest.approx(
        claim(single, "claim-b").support
    )
    assert claim(copied, "claim-a").support == pytest.approx(
        claim(copied, "claim-b").support
    )

def test_dependent_chain_does_not_add_independent_evidence():
    baseline = infer(graph([
        AssertionTriple("a", "attribute", "claim-a"),
        AssertionTriple("b", "attribute", "claim-b"),
    ]))

    chained = infer(graph(
        [
            AssertionTriple("a1", "attribute", "claim-a"),
            AssertionTriple("a2", "attribute", "claim-a"),
            AssertionTriple("a3", "attribute", "claim-a"),
            AssertionTriple("b", "attribute", "claim-b"),
        ],
        {
            ("a1", "a2"): 1.0,
            ("a2", "a3"): 1.0,
        },
        exact_equivalence={
            ("a1", "a2"),
            ("a2", "a3"),
        },
    ))

    baseline_ratio = (
        claim(baseline, "claim-a").support
        / claim(baseline, "claim-b").support
    )
    chained_ratio = (
        claim(chained, "claim-a").support
        / claim(chained, "claim-b").support
    )

    assert chained_ratio == pytest.approx(baseline_ratio)


def exact_equivalence_graph(copies, dependency=0.0):
    return graph(
        [
            *[AssertionTriple(f"a{i}", "x", "yes") for i in range(copies)],
            AssertionTriple("b", "x", "yes"),
            AssertionTriple("c", "x", "no"),
        ],
        {(f"a{i}", "b"): dependency for i in range(copies)},
        exact_equivalence={(f"a{i}", f"a{i+1}") for i in range(copies - 1)},
    )


def test_exact_equivalence_partial_dependency():
    baseline = inference_module._independence(exact_equivalence_graph(1, 0.5))["yes"]
    copied = inference_module._independence(exact_equivalence_graph(3, 0.5))["yes"]
    assert sum(copied.values()) == pytest.approx(sum(baseline.values()))
    assert copied["b"] == pytest.approx(baseline["b"])


@pytest.mark.parametrize("copies", [(1, 1), (2, 1), (1, 3), (3, 5), (6, 2)])
@pytest.mark.parametrize("dependency", [0.0, 0.25, 0.5, 1.0])
@pytest.mark.parametrize("weight", [0.0, 0.7])
def test_exact_equivalence_representation(copies, dependency, weight):
    def run(counts):
        members = {
            "a": [f"a{i}" for i in range(counts[0])],
            "b": [f"b{i}" for i in range(counts[1])],
            "c": ["c"],
        }
        profiles = {
            "a": [("x", "yes"), ("y", "red")],
            "b": [("x", "yes"), ("y", "blue")],
            "c": [("x", "no"), ("y", "blue")],
        }
        value = graph(
            [AssertionTriple(source, attribute, claim_id)
             for group, sources in members.items() for source in sources
             for attribute, claim_id in profiles[group]],
            {(a, b): dependency for a in members["a"] for b in members["b"]},
            exact_equivalence={edge for sources in members.values()
                     for edge in zip(sources, sources[1:])},
        )
        return infer(value, propagation_weight=weight), members

    baseline, baseline_members = run((1, 1))
    expanded, members = run(copies)
    assert expanded.metadata.iterations == baseline.metadata.iterations
    assert expanded.metadata.convergence_delta == baseline.metadata.convergence_delta
    for group, sources in members.items():
        expected = next(item.reliability for item in baseline.source_reliability
                        if item.source_id == baseline_members[group][0])
        assert sum(item.reliability for item in expanded.source_reliability
                   if item.source_id in sources) == pytest.approx(expected)
    for expected in baseline.claim_support:
        actual = claim(expanded, expected.claim_id)
        assert actual.support == expected.support
        # Match the evaluator's canonical, sequential contribution check.
        total = 0.0
        for item in sorted(actual.supporting_sources, key=lambda item: item.source_id):
            total += item.contribution
        assert total == actual.support
        assert actual.agreement_weight == expected.agreement_weight
        assert actual.estimated_independent_support_count == pytest.approx(
            expected.estimated_independent_support_count
        )
        assert actual.is_attribute_max_support == expected.is_attribute_max_support
        for group, sources in members.items():
            for field in ("independence", "contribution"):
                assert sum(getattr(item, field) for item in actual.supporting_sources
                           if item.source_id in sources) == pytest.approx(
                    sum(getattr(item, field) for item in expected.supporting_sources
                        if item.source_id in baseline_members[group])
                )


@pytest.mark.parametrize("different", ["claims", "dependency"])
def test_heterogeneous_exact_equivalence(different):
    assertions = [AssertionTriple(source, "x", "yes") for source in ("a", "b", "c")]
    dependencies = {}
    if different == "claims":
        assertions.append(AssertionTriple("a", "y", "other"))
    else:
        dependencies[("a", "c")] = 0.5
    value = graph(assertions, dependencies, exact_equivalence={("a", "b")})
    with pytest.raises(InferenceError, match="heterogeneous exact equivalence"):
        infer(value)


@pytest.mark.parametrize("count", [2, 3, 6, 17, 49])
def test_exact_equivalence_ties(count):
    sources = [f"a{i:02}" for i in range(count)]
    result = infer(graph(
        [*[AssertionTriple(source, "x", "yes") for source in sources],
         AssertionTriple("b", "x", "no")],
        exact_equivalence=set(zip(sources, sources[1:])),
    ))
    assert all(item.support == 0.25 and item.is_attribute_max_support
               for item in result.claim_support)
    assert sum(item.reliability for item in result.source_reliability
               if item.source_id in sources) == pytest.approx(0.5)


def test_exact_equivalence_coverage_does_not_change_scores():
    original = exact_equivalence_graph(3, 0.5)
    changed = replace(original, source_pairs={
        key: replace(value, weighted_signal_coverage=index / len(original.source_pairs))
        for index, (key, value) in enumerate(original.source_pairs.items())
    })
    first, second = infer(original), infer(changed)
    assert first.source_reliability == second.source_reliability
    assert first.metadata == second.metadata
    assert [(item.support, item.agreement_weight) for item in first.claim_support] == [
        (item.support, item.agreement_weight) for item in second.claim_support
    ]


@pytest.mark.parametrize("topology", ["chain", "star", "cycle", "clique"])
def test_exact_equivalence_topology(topology):
    original = exact_equivalence_graph(6, 0.5)
    sources = [f"a{i}" for i in range(6)]
    edges = set(zip(sources, sources[1:]))
    if topology == "star":
        edges = {(sources[0], other) for other in sources[1:]}
    elif topology == "cycle":
        edges.add((sources[0], sources[-1]))
    elif topology == "clique":
        edges = {(a, b) for index, a in enumerate(sources) for b in sources[index + 1:]}
    changed = replace(original, source_pairs={
        key: replace(value, exact_equivalence=key in edges)
        for key, value in original.source_pairs.items()
    })
    assert infer(changed) == infer(original)


def test_exact_equivalence_propagation():
    def ratio(copies, weight):
        result = infer(exact_equivalence_graph(copies), propagation_weight=weight)
        return claim(result, "yes").support / claim(result, "no").support

    # Independence and agreement alone preserve the ratio; recursion must too.
    assert ratio(3, 0.0) == pytest.approx(ratio(1, 0.0))
    assert ratio(3, 0.7) == pytest.approx(ratio(1, 0.7))


def test_scalar_dependency_is_not_exact_equivalence():
    value = graph(
        [AssertionTriple(source, "x", "yes") for source in ("a", "b", "c")],
        {("a", "b"): 1.0, ("b", "c"): 1.0},
    )
    assert inference_module._independence(value)["yes"] == {
        "a": 0.5, "b": 1 / 3, "c": 0.5,
    }


def test_exact_equivalence_order():
    value = exact_equivalence_graph(3, 0.5)
    reordered = build_graph(
        [
            AssertionTriple(source, value.claim_to_attribute[claim_id], claim_id)
            for source in reversed(value.sources)
            for claim_id in reversed(value.source_to_claims[source])
        ],
        [SourcePair(a, b, pair.dependency, pair.weighted_signal_coverage, pair.exact_equivalence)
         for (a, b), pair in reversed(list(value.source_pairs.items()))],
    )
    assert infer(value) == infer(reordered)


def test_independent_corroboration():
    single = infer(graph([
        AssertionTriple("a", "x", "yes"), AssertionTriple("c", "x", "no"),
    ]))
    corroborated = infer(exact_equivalence_graph(1))
    assert (claim(corroborated, "yes").support / claim(corroborated, "no").support
            > claim(single, "yes").support / claim(single, "no").support)


@pytest.mark.parametrize("count", [3, 6, 49])
def test_exact_equivalence_effective_count(count):
    sources = [f"s{i:02}" for i in range(count)]
    edges = set(zip(sources, sources[1:]))
    result = infer(graph(
        [AssertionTriple(source, "x", "yes") for source in sources],
        {edge: 1.0 for edge in edges},
        exact_equivalence=edges,
    ))
    assert claim(result, "yes").estimated_independent_support_count == pytest.approx(1.0)
    assert claim(result, "yes").estimated_independent_support_count >= 1.0
    assert claim(result, "yes").support == 1.0
