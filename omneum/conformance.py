import argparse
import json
import math
from datetime import datetime
from itertools import combinations

from . import dependency, inference
from .client import _map_assertion_evaluation
from .compatibility import load_contract
from .engine_graph import AssertionTriple, SourcePair, build_graph
from .information import Claim, Observation, Retrieval, Source, SourceReference


def compare(actual, expected, relative, absolute):
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or set(actual) != set(expected):
            raise AssertionError("conformance object keys differ")
        for key in expected:
            compare(actual[key], expected[key], relative, absolute)
    elif isinstance(expected, (tuple, list)):
        if len(actual) != len(expected):
            raise AssertionError("conformance sequence lengths differ")
        for actual_item, expected_item in zip(actual, expected):
            compare(actual_item, expected_item, relative, absolute)
    elif isinstance(expected, bool) or expected is None:
        if actual is not expected:
            raise AssertionError("conformance boolean/null mismatch")
    elif isinstance(expected, (int, float)):
        if isinstance(actual, bool) or not math.isfinite(actual) or not math.isclose(actual, expected, rel_tol=relative, abs_tol=absolute):
            raise AssertionError("conformance numeric mismatch")
    elif actual != expected:
        raise AssertionError("conformance value mismatch")


def config(weights):
    return dependency.DependencyEstimatorConfig(
        **{name + "_weight": float(weights.get(name, 0)) for name in dependency.SIGNALS},
        temporal_window_seconds=7200.0,
    )


def propagation(case, relative, absolute):
    sources = sorted({row[0] for row in case["assertions"]})
    pairs = [
        SourcePair(
            first, second,
            case["dependency"].get(first, {}).get(second, 0.0),
            case["coverage"].get(first, {}).get(second, 0.0),
        )
        for first, second in combinations(sources, 2)
    ]
    graph = build_graph([AssertionTriple(*row) for row in case["assertions"]], pairs)
    expected = case["expected"]
    if "error" in expected:
        if expected != {"error": "nonconvergence"}:
            raise ValueError("unsupported expected failure")
        try:
            inference.infer(graph)
        except inference.InferenceError as error:
            if str(error) != "inference did not converge":
                raise
        else:
            raise AssertionError("expected nonconvergence")
        return
    result = inference.infer(graph)
    compare({item.source_id: item.reliability for item in result.source_reliability}, expected["reliability"], relative, absolute)
    if result.metadata.iterations != expected["iterations"] or not result.metadata.converged:
        raise AssertionError("convergence mismatch")
    compare(result.metadata.convergence_delta, expected["delta"], relative, absolute)
    claims = {}
    for item in result.claim_support:
        claims[item.claim_id] = {
            "support": item.support, "agreement": item.agreement_weight,
            "independence": {source.source_id: source.independence for source in item.supporting_sources},
            "contributions": {source.source_id: source.contribution for source in item.supporting_sources},
            "is_maximum": item.is_attribute_max_support,
            "conflicts": sorted(other.claim_id for other in item.conflicting_claims),
            "effective_count": item.estimated_independent_support_count,
            "coverage": item.dependency_signal_coverage,
        }
    compare(claims, expected["claims"], relative, absolute)


def fusion(case, relative, absolute):
    signals = dependency.DependencySignalScores(
        **{name: float(case["signals"][name]) for name in dependency.SIGNALS},
        **{name + "_observable": case["observable"][name] for name in dependency.SIGNALS},
    )
    compare(
        dependency.combine_dependency(signals, config(case["weights"]), excluded_signals=case["excluded"]),
        case["expected"], relative, absolute,
    )


def records(case, relative, absolute):
    identities = sorted(
        {source["source_id"] for source in case["sources"]}
        | {value for item in case["evidence"] for value in (item["upstream_source_ids"] or [])}
    )
    names = {value: "source-" + str(index) + ".example" for index, value in enumerate(identities)}
    sources = {item["source_id"]: Source("web_publisher", names[item["source_id"]], item["owner_id"]) for item in case["sources"]}
    def references(values):
        return None if values is None else tuple(SourceReference("web_publisher", names[value]) for value in values)
    evidence = {item["assertion_id"]: item for item in case["evidence"]}
    observations = []
    for assertion in case["assertions"]:
        item = evidence[assertion["assertion_id"]]
        observations.append(Observation(
            assertion["assertion_id"], sources[assertion["source_id"]],
            Claim("service", assertion["entity"], assertion["attribute"], assertion["value"]),
            datetime.fromisoformat(item["observed_at"]),
            source_modified_at=datetime.fromisoformat(item["source_modified_at"]) if item["source_modified_at"] else None,
            upstream_sources=references(item["upstream_source_ids"]),
            cited_sources=references(item["cited_source_ids"]),
            parent_assertion_ids=None if item["parent_assertion_ids"] is None else tuple(item["parent_assertion_ids"]),
            retrievals=tuple(Retrieval(
                value["retrieval_id"], value["kind"], value["resource_id"], datetime.fromisoformat(value["retrieved_at"]),
            ) for value in item["retrievals"]),
        ))
    pairs, _ = dependency.estimate_dependencies(tuple(sources.values()), tuple(observations), config(case["weights"]))
    selected = next(pair for pair in pairs if {pair.source_a.identifier, pair.source_b.identifier} == {names["a"], names["b"]})
    expected = case["expected"]
    compare({name: getattr(selected.signals, name) for name in dependency.SIGNALS}, expected["signals"], relative, absolute)
    compare({name: getattr(selected.signals, name + "_observable") for name in dependency.SIGNALS}, expected["observable"], relative, absolute)
    compare(selected.dependency, expected["dependency"], relative, absolute)
    compare(selected.weighted_signal_coverage, expected["coverage"], relative, absolute)
    compare(dependency.combine_dependency(selected.signals, config(case["weights"]), excluded_signals=tuple(expected["excluded"])), (selected.dependency, selected.weighted_signal_coverage), relative, absolute)


def clusters(case, relative, absolute):
    matrix = case["dependency"]
    sources = {name: Source("web_publisher", name + ".example") for name in sorted(matrix)}
    references = {name: SourceReference(source.kind, source.identifier) for name, source in sources.items()}
    blank = dependency.DependencySignalScores(
        **{name: 0.0 for name in dependency.SIGNALS},
        **{name + "_observable": False for name in dependency.SIGNALS},
    )
    pairs = tuple(dependency.PairwiseDependencyResult(
        references[first], references[second], blank, float(matrix[first][second]), 0.0,
    ) for first, second in combinations(sources, 2))
    triples = [
        AssertionTriple(source, "selected" if source in case["sources"] else "other-" + source, "selected" if source in case["sources"] else "other-" + source)
        for source in sources
    ]
    graph = build_graph(triples, [
        SourcePair(first, second, float(matrix[first][second]), 0.0)
        for first, second in combinations(sources, 2)
    ])
    mapped = _map_assertion_evaluation(
        inference.infer(graph), sources,
        {claim: Claim("service", "entity", claim, "value") for claim in graph.claims},
        pairs, float(case["threshold"]),
    )
    selected = next(claim for claim in mapped.claim_support if claim.claim.attribute == "selected")
    actual = {frozenset(source.identifier.removesuffix(".example") for source in group.sources) for group in selected.dependency_clusters}
    if actual != {frozenset(group) for group in case["expected"]}:
        raise AssertionError("claim-induced clusters differ")
    induced = tuple(pair for pair in pairs if pair.source_a.identifier.removesuffix(".example") in case["sources"] and pair.source_b.identifier.removesuffix(".example") in case["sources"])
    groups = dependency._clusters(tuple((references[name].kind, references[name].identifier) for name in sorted(case["sources"])), induced, float(case["threshold"]))
    if {frozenset(source.identifier.removesuffix(".example") for source in group.sources) for group in groups} != actual:
        raise AssertionError("estimator clusters differ")


def check(checkout, pin=None):
    pin, manifest, fixtures = load_contract(checkout, pin)
    numerical = manifest["numerical_contract"]
    if numerical["arithmetic"] != "binary64":
        raise ValueError("unsupported arithmetic")
    if numerical["convergence_tolerance"] != inference.CONVERGENCE_TOLERANCE or numerical["max_iterations"] != inference.MAX_ITERATIONS:
        raise AssertionError("production convergence settings differ")
    relative = numerical["fixture_relative_tolerance"]
    absolute = numerical["fixture_absolute_tolerance"]
    if any(type(value) not in (int, float) or not math.isfinite(value) or value < 0 for value in (relative, absolute)):
        raise ValueError("invalid comparison tolerance")
    runners = {"propagation": propagation, "fusion": fusion, "records": records, "clusters": clusters}
    counts = {}
    for fixture in fixtures:
        if "relative_tolerance" in fixture and (fixture["relative_tolerance"], fixture["absolute_tolerance"]) != (relative, absolute):
            raise ValueError("fixture tolerances disagree")
        groups = set(fixture) - {"algorithm_version", "fixture_revision", "relative_tolerance", "absolute_tolerance"}
        if not groups or groups - runners.keys() or groups & counts.keys():
            raise ValueError("unsupported or duplicate fixture group")
        for group in sorted(groups):
            cases = fixture[group]
            if not isinstance(cases, list) or not cases or len({case["name"] for case in cases}) != len(cases):
                raise ValueError("empty or duplicate conformance cases")
            for case in cases:
                try:
                    runners[group](case, relative, absolute)
                except Exception as error:
                    raise AssertionError("conformance failed: " + group + "/" + case["name"]) from error
            counts[group] = len(cases)
    if set(counts) != set(runners):
        raise ValueError("incomplete fixture coverage")
    return {"compatibility": pin, "cases": counts, "passed": True}


def main():
    parser = argparse.ArgumentParser(description="Verify the independently implemented algorithm against committed specification fixtures")
    parser.add_argument("--spec-checkout", required=True)
    parser.add_argument("--pin")
    arguments = parser.parse_args()
    from .compatibility import load_pin
    print(json.dumps(check(arguments.spec_checkout, load_pin(arguments.pin) if arguments.pin else None), indent=2))


if __name__ == "__main__":
    main()
