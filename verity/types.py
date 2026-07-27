from dataclasses import dataclass


# Source Credibility

@dataclass(slots=True)
class SourceScore:
    """
    Credibility assigned to a source after inference.
    """

    source_id: str
    credibility: float


# Claim Support

@dataclass(slots=True)
class ConflictingClaim:
    """
    A competing claim within the same attribute group.
    """

    claim_id: str
    support: float


@dataclass(slots=True)
class ClaimSupport:
    """
    Support assigned to a claim after inference.
    """

    attribute_id: str
    claim_id: str

    support: float

    is_attribute_max_support: bool

    conflicting_claims: list[ConflictingClaim]


# Summary

@dataclass(slots=True)
class GraphSummary:
    """
    Statistics describing the processed graph.
    """

    source_count: int
    claim_count: int
    assertion_count: int


# Metadata

@dataclass(slots=True)
class InferenceMetadata:
    """
    Metadata describing the completed inference run.
    """

    algorithm_version: str

    iterations: int
    converged: bool

    computation_time_ms: int


# Graph

@dataclass(slots=True)
class CredibilityGraph:
    source_to_claims: dict[str, set[str]]
    claim_to_sources: dict[str, set[str]]

    claim_to_attribute: dict[str, str]
    attribute_to_claims: dict[str, set[str]]

    assertion_count: int

    agreement_weights: dict[tuple[str, str], float]


# Engine Output

@dataclass(slots=True)
class InferenceResult:
    """
    Complete output produced by the credibility inference engine.

    This object is transport-independent and is converted into
    protocol responses by the formatter layer.
    """

    summary: GraphSummary

    source_scores: list[SourceScore]

    claim_support: list[ClaimSupport]

    metadata: InferenceMetadata