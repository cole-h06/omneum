from dataclasses import replace
import hashlib
from itertools import combinations
import runpy

import pytest

from omneum import ContextEvaluation, evaluate_context
from omneum.engine_graph import AssertionTriple, SourcePair
from omneum.engine_graph import build_graph as build_inference_graph
from omneum.inference import InferenceResult, infer
from research.braid.adapters.observations import estimator, source_identifier, to_observations
from research.braid.adapters.structural import build_graph
from research.braid.experiments.applied.agent_dataset.dataset import (
    DEPENDENCY_WEIGHTS,
    load_dataset,
)
from research.braid.experiments.applied.agent_dataset.run import run_experiment


def test_agent_dataset():
    result = run_experiment()
    evaluation = result["evaluation"]
    assert isinstance(evaluation, ContextEvaluation)
    assert len(result["observations"]) == 15
    assert len(evaluation.source_reliability) == 5
    assert len(evaluation.claim_support) == 9
    assert len(evaluation.pairwise_dependencies) == 10
    assert evaluation.convergence.algorithm_version == "omneum-v2"
    assert evaluation.convergence.converged
    assert sum(item.reliability for item in evaluation.source_reliability) == pytest.approx(1.0)
    for claim in evaluation.claim_support:
        assert claim.support > 0
        assert sum(item.contribution for item in claim.supporting_sources) == pytest.approx(claim.support)


def test_observation_identity_and_provenance():
    sources, observations = load_dataset()
    first = observations[0].model_copy(update={
        "entity_namespace": "other_namespace",
        "upstream_source_ids": ("external_origin",),
        "cited_source_ids": (),
        "parent_assertion_ids": None,
    })
    converted = to_observations(sources, [first, *observations[1:]])
    assert converted[0].claim.entity_namespace == "other_namespace"
    assert converted[0].source.identifier == source_identifier(first.source_id)
    assert converted[0].upstream_sources[0].identifier == source_identifier("external_origin")
    assert converted[0].cited_sources == ()
    assert converted[0].parent_observation_ids is None
    for original, value in zip([first, *observations[1:]], converted):
        assert value.observation_id == original.assertion_id
        assert value.observed_at == original.observed_at
        assert value.source_modified_at == original.source_modified_at
        assert value.claim.value == original.value
        assert value.metadata == original.metadata
        assert value.dependency_signals == original.dependency_signals
        assert value.source.owner_id == next(
            source.owner_id for source in sources if source.source_id == original.source_id
        )


def test_structural_matrix_parity():
    assertions = [("a", "property", "yes"), ("b", "property", "yes"), ("c", "property", "no")]
    dependency = {
        "a": {"a": 0.0, "b": 0.9, "c": 0.2},
        "b": {"a": 0.9, "b": 0.0, "c": 0.1},
        "c": {"a": 0.2, "b": 0.1, "c": 0.0},
    }
    coverage = {a: {b: 0.0 if a == b else 0.75 for b in dependency} for a in dependency}
    graph = build_graph(assertions, dependency, coverage)
    expected = build_inference_graph(
        [AssertionTriple(*row) for row in assertions],
        [
            SourcePair(a, b, dependency[a][b], coverage[a][b])
            for a, b in combinations(sorted(dependency), 2)
        ],
    )
    assert graph == expected
    assert infer(graph) == infer(expected)
    assert infer(graph) == infer(build_graph(list(reversed(assertions)), dependency, coverage))


@pytest.mark.parametrize("matrix,message", [
    ({"a": {"a": 0.0}, "b": {"b": 0.0}}, "exactly the graph sources"),
    ({"a": {"a": 0.0, "b": 0.1}, "b": {"a": 0.2, "b": 0.0}}, "symmetric"),
    ({"a": {"a": 1.0, "b": 0.0}, "b": {"a": 0.0, "b": 0.0}}, "diagonal"),
])
def test_invalid_matrix(matrix, message):
    with pytest.raises(ValueError, match=message):
        build_graph([("a", "attribute", "claim"), ("b", "attribute", "claim")], matrix)


def test_explicit_equivalence():
    assertions = [("a", "attribute", "claim"), ("b", "attribute", "claim")]
    graph = build_graph(assertions, exact_equivalences=[("b", "a")])
    assert graph.source_pairs["a", "b"].exact_equivalence
    assert infer(graph).claim_support[0].estimated_independent_support_count == 1.0
    assert infer(build_graph(assertions)).claim_support[0].estimated_independent_support_count == 2.0
    with pytest.raises(ValueError, match="distinct graph sources"):
        build_graph(assertions, exact_equivalences=[("a", "unknown")])


@pytest.mark.parametrize("name", [
    "single_source", "shared_claims", "claim_volume", "complex_graph",
    "conflicting_claims", "propagation_topology", "independent_sources",
    "dependent_sources", "mixed_dependencies",
])
def test_direct_experiment(name):
    namespace = runpy.run_module(f"research.braid.experiments.algorithm.{name}", run_name="__main__")
    results = [value for value in namespace.values() if isinstance(value, InferenceResult)]
    assert results
    assert all(result.metadata.algorithm_version == "omneum-v2" for result in results)
    assert all(result.metadata.converged for result in results)


def test_workflow_parity():
    pytest.importorskip("langgraph")
    from research.braid.experiments.applied.agent_dataset.workflow.pipeline import run_workflow

    sequential = run_experiment()
    workflow = run_workflow()
    assert workflow["observations"] == sequential["observations"]
    assert replace(workflow["evaluation"], evaluation_latency_ms=None) == replace(
        sequential["evaluation"], evaluation_latency_ms=None,
    )


def test_enterprise_fixtures_and_repeatability():
    pytest.importorskip("langgraph")
    from research.braid.experiments.applied.agent_dataset.enterprise.data import FIXTURES, load_manifest
    from research.braid.experiments.applied.agent_dataset.enterprise.workflow import run_enterprise

    manifest = load_manifest()
    for name, digest in manifest["snapshots"].items():
        assert hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest() == digest
    first = run_enterprise()
    second = run_enterprise()
    assert len(first["observations"]) == 15
    assert first["observations"] == second["observations"]
    assert replace(first["evaluation"], evaluation_latency_ms=None) == replace(
        second["evaluation"], evaluation_latency_ms=None,
    )
    converted = to_observations(first["sources"], first["observations"])
    assert replace(first["evaluation"], evaluation_latency_ms=None) == replace(
        evaluate_context(converted, estimator=estimator(DEPENDENCY_WEIGHTS)),
        evaluation_latency_ms=None,
    )
    assert len(first["evaluation"].claim_support) == 6
    for original, value in zip(first["observations"], converted):
        assert value.observed_at == original.observed_at
        assert value.source_modified_at == original.source_modified_at
        assert value.parent_observation_ids == original.parent_assertion_ids
        assert len(value.retrievals) == len(original.retrievals)
        for before, after in zip(original.retrievals, value.retrievals):
            assert (after.resource_id, after.kind, after.retrieved_at, after.fields) == (
                before.resource_id, before.kind, before.retrieved_at, before.fields,
            )
