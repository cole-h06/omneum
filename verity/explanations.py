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
_SIGNALS = (
    ("provenance", "Shared provenance"),
    ("lineage", "Citation or lineage relationship"),
    ("ownership", "Shared ownership"),
    ("temporal", "Close timing"),
    ("structural", "Assertion overlap"),
)


def explain_claim(
    result: ClaimSupportResult,
    *,
    source_labels: Mapping[Source, str] | None = None,
) -> str:
    """Render one validated claim result using local information only."""
    if type(result) is not ClaimSupportResult:
        raise TypeError("result must be a ClaimSupportResult")
    _labels(source_labels)

    claim = result.claim
    lines = [
        f"{_attribute(claim.attribute)} = {_value(claim.value)}",
        f"Support: {result.support:.2f}",
        "",
        _supported(result.supporting_source_count),
        "Estimated independent support: "
        f"{result.estimated_independent_support_count:.2f}.",
    ]
    if result.dependency_confidence is not None:
        lines.append(
            "Dependency signal coverage: "
            f"{result.dependency_confidence:.2f}."
        )
    if result.dependency_clusters is not None:
        lines.append(
            f"Dependency {_group(len(result.dependency_clusters))}: "
            f"{len(result.dependency_clusters)}."
        )
    if result.conflicting_claims:
        conflicts = "; ".join(
            f"{_value(item.claim.value)} (support {item.support:.2f})"
            for item in result.conflicting_claims
        )
        lines.append(f"Conflicts: {conflicts}.")
    if result.is_attribute_max_support:
        lines.append("✓ Highest-supported competing value.")
    return "\n".join(lines)


def explain_dependency(
    result: PairwiseDependencyResult,
    *,
    source_labels: Mapping[Source, str] | None = None,
) -> str:
    """Render one validated pair result using local signal telemetry."""
    if type(result) is not PairwiseDependencyResult:
        raise TypeError("result must be a PairwiseDependencyResult")
    labels = _labels(source_labels)
    source_a = _source_label(result.source_a.kind, result.source_a.identifier, labels)
    source_b = _source_label(result.source_b.kind, result.source_b.identifier, labels)
    positive = [
        phrase
        for name, phrase in _SIGNALS
        if getattr(result.signals, f"{name}_observable")
        and getattr(result.signals, name) > 0.0
    ]
    description = (
        _signal_sentence(positive)
        if positive
        else "No positive dependency signal was observed."
    )
    return "\n".join((
        f"{source_a} ↔ {source_b}",
        "",
        f"Estimated independence: {1.0 - result.dependency:.2f}",
        description,
    ))


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


def _supported(count):
    noun = "source" if count == 1 else "sources"
    return f"Supported by {count} {noun}."


def _group(count):
    return "group" if count == 1 else "groups"


def _signal_sentence(values):
    if len(values) == 1:
        return f"{values[0]} detected."
    lowered = [values[0], *(value[0].lower() + value[1:] for value in values[1:])]
    if len(lowered) == 2:
        return f"{lowered[0]} and {lowered[1]} detected."
    return f"{', '.join(lowered[:-1])}, and {lowered[-1]} detected."
