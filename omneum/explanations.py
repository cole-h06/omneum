import unicodedata
from collections.abc import Mapping

import rfc8785

from .canonicalization import canonicalize_source
from .client import ClaimSupportResult
from .dependency import PairwiseDependencyResult
from .information import Source


_INTERNAL_LABELS = {
    "internal_resource": "Internal resource",
    "internal_service": "Internal service",
    "database": "Database",
}



def explain_evaluation(evaluation) -> str:
    """Render an Omneum evaluation grouped by attribute, ranked by support."""
    latency = evaluation.evaluation_latency_ms

    lines = ["Omneum Evaluation"]

    if latency is not None:
        lines.append(f"Evaluation latency: {latency:.1f} ms")

    groups = {}
    for result in evaluation.claim_support:
        key = (
            result.claim.entity_namespace,
            result.claim.entity,
            result.claim.attribute,
        )
        groups.setdefault(key, []).append(result)

    for (_, _, attribute), results in groups.items():
        lines.extend(("", _attribute(attribute)))

        for result in sorted(results, key=lambda r: r.support, reverse=True):
            lines.extend(
                (
                    "",
                    f"  {_value(result.claim.value)}",
                    f"  Support: {result.support:.2f}",
                    (
                        "  Supporting sources: "
                        f"{result.supporting_source_count}"
                    ),
                    (
                        "  Estimated independent support: "
                        f"{result.estimated_independent_support_count:.2f}"
                    ),
                )
            )

            if result.dependency_signal_coverage is None:
                lines.append(
                    "  Dependency signal coverage: unavailable"
                )
            else:
                lines.append(
                    "  Dependency signal coverage: "
                    f"{result.dependency_signal_coverage:.2f}"
                )

            if result.conflicting_claims:
                lines.append("  Conflicting values:")
                for conflict in result.conflicting_claims:
                    lines.append(
                        f"    {_value(conflict.claim.value)} (support {conflict.support:.2f})"
                    )

            explanation = _claim_explanation(
                result,
                include_conflicts=False,
            )
            lines.extend(("", "  Explanation:", f"    {explanation}"))


    return "\n".join(lines)


def explain_claim(
    result: ClaimSupportResult,
    *,
    source_labels: Mapping[Source, str] | None = None,
) -> str:
    """Render a claim result with deterministic metrics and interpretation."""
    if type(result) is not ClaimSupportResult:
        raise TypeError("result must be a ClaimSupportResult")

    _labels(source_labels)

    claim = result.claim
    lines = [
        "Omneum Evaluation",
        "",
        f"Claim: {_attribute(claim.attribute)} = {_value(claim.value)}",
        f"Support: {result.support:.2f}",
        f"Agreement weight: {result.agreement_weight:.2f}",
        f"Supporting sources: {result.supporting_source_count}",
        (
            "Estimated independent support: "
            f"{result.estimated_independent_support_count:.2f}"
        ),
    ]

    if result.dependency_signal_coverage is None:
        lines.append("Source-dependency comparison: unavailable")
    else:
        lines.append(
            "Dependency signal coverage: "
            f"{result.dependency_signal_coverage:.2f}"
        )

    if result.conflicting_claims:
        noun = (
            "value"
            if len(result.conflicting_claims) == 1
            else "values"
        )
        lines.append(
            f"Conflicting {noun}: "
            + ", ".join(
                _value(item.claim.value)
                for item in result.conflicting_claims
            )
        )

    lines.extend(("", "Explanation:"))
    lines.append(_claim_explanation(result))

    return "\n".join(lines)


def _claim_explanation(
    result: ClaimSupportResult,
    *,
    include_conflicts: bool = True,
) -> str:
    count = result.supporting_source_count
    independent = result.estimated_independent_support_count
    confidence = result.dependency_signal_coverage

    if count == 1:
        sentences = [
            "One source supports this claim."
        ]
    else:
        sentences = [
            f"{count} sources support this claim, "
            f"with an estimated {independent:.2f} independent sources."
        ]

        if confidence is None:
            sentences.append(
                "No source-dependency signals were available "
                "to assess source independence."
            )
        elif confidence == 0.0:
            sentences.append(
                "No source-dependency signals were observed "
                "for this comparison."
            )
        elif independent < count - 0.01:
            sentences.append(
                "The available dependency signals indicate "
                "that some supporting sources are related."
            )
        else:
            sentences.append(
                "The available dependency signals do not "
                "indicate substantial source dependence."
            )

    if include_conflicts and result.conflicting_claims:
        conflict_count = len(result.conflicting_claims)
        noun = "value" if conflict_count == 1 else "values"
        verb = "was" if conflict_count == 1 else "were"
        sentences.append(
            f"{conflict_count} conflicting {noun} "
            f"{verb} identified for the same attribute."
        )

    return " ".join(sentences)



def explain_dependency(
    result: PairwiseDependencyResult,
    *,
    source_labels: Mapping[Source, str] | None = None,
) -> str:
    """Render one validated pair result using local signal telemetry."""
    if type(result) is not PairwiseDependencyResult:
        raise TypeError("result must be a PairwiseDependencyResult")

    labels = _labels(source_labels)
    source_a = _source_label(
        result.source_a.kind,
        result.source_a.identifier,
        labels,
    )
    source_b = _source_label(
        result.source_b.kind,
        result.source_b.identifier,
        labels,
    )
    facts = _evidence(result)

    lines = [
        f"{source_a} ↔ {source_b}",
        "",
        f"Independence: {1.0 - result.dependency:.2f}",
        "",
    ]
    lines.extend(f"• {fact}" for fact in facts or ("None observed",))
    return "\n".join(lines)

def _labels(value):
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError("source_labels must be a mapping or None")

    labels = {}
    for source, label in value.items():
        if type(source) is not Source:
            raise TypeError("source_labels must contain Source keys")
        if type(label) is not str:
            raise TypeError("source labels must be strings")
        if not label or any(
            unicodedata.category(character) == "Cc"
            for character in label
        ):
            raise ValueError("source label is invalid")

        try:
            identity = (
                source.kind,
                canonicalize_source(source.kind, source.identifier),
            )
        except Exception:
            raise ValueError("source label source is invalid") from None

        if identity in labels:
            raise ValueError("source labels contain duplicate sources")

        labels[identity] = label

    return labels


def _source_label(kind, identifier, labels):
    canonical = canonicalize_source(kind, identifier)
    supplied = labels.get((kind, canonical))

    if supplied is not None:
        return supplied
    if kind in _INTERNAL_LABELS:
        return _INTERNAL_LABELS[kind]

    return canonical


def _attribute(value):
    return value.replace("_", " ").capitalize()


def _value(value):
    serialized = rfc8785.dumps(value).decode("utf-8")
    if type(value) is str:
        return serialized[1:-1]
    return serialized


def _supporting(count):
    noun = "source" if count == 1 else "sources"
    return f"Supporting {noun}: {count}"


def _claim_interpretation(result):
    count = result.supporting_source_count
    independent = result.estimated_independent_support_count

    noun = "source" if count == 1 else "sources"

    if count == 1:
        lines = [
            "One source supports this claim.",
            "No source-dependency comparison was available.",
        ]
    else:
        lines = [
            f"{count} sources support this claim.",
            f"Estimated independent support: {independent:.2f}.",
        ]

        if independent < count - 0.01:
            lines.append(
                "Some supporting sources appear dependent."
            )

    conflict_count = len(result.conflicting_claims)
    if conflict_count:
        noun = "value" if conflict_count == 1 else "values"
        verb = "was" if conflict_count == 1 else "were"
        lines.append(
            f"{conflict_count} conflicting {noun} {verb} identified."
        )

    return lines


def _evidence(result):
    evidence = result.evidence
    if evidence is None:
        return _signal_fallback(result)

    facts = []

    if evidence.source_a_upstream_of_source_b:
        facts.append("Upstream source relationship")
    if evidence.source_b_upstream_of_source_a:
        facts.append("Upstream source relationship")

    if evidence.source_a_cites_source_b:
        facts.append("Direct citation")
    if evidence.source_b_cites_source_a:
        facts.append("Direct citation")

    if evidence.source_a_parent_count:
        facts.append(_derived(evidence.source_a_parent_count))
    if evidence.source_b_parent_count:
        facts.append(_derived(evidence.source_b_parent_count))

    if evidence.same_owner:
        facts.append("Same owner")

    deltas = tuple(sorted(set(evidence.qualifying_time_deltas_seconds)))
    if len(deltas) == 1:
        facts.append(f"Updated {_duration(deltas[0])} apart")
    elif deltas:
        facts.append(
            "Update gaps: "
            + ", ".join(_duration(value) for value in deltas)
        )

    if evidence.matching_claim_count:
        count = evidence.matching_claim_count
        noun = "claim" if count == 1 else "claims"
        facts.append(f"{count} matching {noun}")

    return facts


def _derived(count):
    noun = "assertion" if count == 1 else "assertions"
    return f"{count} derived {noun}"


def _duration(seconds):
    for unit, size in (
        ("day", 86_400),
        ("hour", 3_600),
        ("minute", 60),
    ):
        if seconds % size == 0:
            count = int(seconds / size)
            noun = unit if count == 1 else f"{unit}s"
            return f"{count} {noun}"

    return f"{seconds:g} seconds"


def _signal_fallback(result):
    signals = result.signals

    positive = any(
        getattr(signals, f"{name}_observable")
        and getattr(signals, name) > 0.0
        for name in (
            "upstream",
            "citation",
            "assertion_lineage",
            "ownership",
            "temporal",
            "graph",
        )
    )

    return ["Details unavailable"] if positive else []
