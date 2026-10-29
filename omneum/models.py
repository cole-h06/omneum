import uuid
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)


OmneumCode = Literal[
    "request_too_large",
    "invalid_request",
    "authentication_required",
    "permission_denied",
    "unsupported_protocol_version",
    "deployment_mismatch",
    "voprf_key_version_mismatch",
    "unsupported_voprf_mode",
    "unsupported_voprf_ciphersuite",
    "unsupported_linkage_encoding_version",
    "invalid_blinded_element",
    "invalid_graph",
    "rate_limited",
    "server_busy",
    "request_timeout",
    "evaluation_failed",
    "assertion_evaluation_failed",
    "internal_error",
]


def _canonical_deployment_id(value: str) -> str:
    prefix = "urn:uuid:"
    if not value.startswith(prefix):
        raise ValueError("deployment_id must be a canonical UUID URN")
    try:
        parsed = uuid.UUID(value[len(prefix):])
    except ValueError:
        raise ValueError(
            "deployment_id must be a canonical UUID URN"
        ) from None
    if value != f"{prefix}{parsed}":
        raise ValueError("deployment_id must be a canonical UUID URN")
    return value


class EvaluateVOPRFRequest(BaseModel):
    """Single-element RFC 9497 VOPRF evaluation request."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    protocol_version: str = Field(description="Omneum protocol version. Must be v1.")
    deployment_id: str = Field(description=(
        "Deployment identifier from the initialized client configuration or ping. "
        "Must be a canonical lowercase urn:uuid:… value matching this server."
    ))
    voprf_key_version: int = Field(
        ge=1,
        le=2**32 - 1,
        description="VOPRF key version matching this deployment's configured key version.",
    )
    voprf_mode: str = Field(description="VOPRF mode. Must be voprf.")
    voprf_ciphersuite: str = Field(description=(
        "VOPRF ciphersuite. Must be ristretto255-SHA512."
    ))
    linkage_encoding_version: int = Field(description=(
        "Omneum linkage encoding version. Must be 1."
    ))
    blinded_element: str = Field(description=(
        "One serialized 32-byte RFC 9497 blinded Ristretto255 element, encoded as "
        "canonical unpadded base64url: 43 characters using A-Z, a-z, 0-9, _, and -. "
        "Generate it with the Omneum client's blinding operation; do not submit plaintext."
    ))

    @field_validator("deployment_id")
    @classmethod
    def validate_deployment_id(cls, value: str) -> str:
        return _canonical_deployment_id(value)


class EvaluateVOPRFResponse(BaseModel):
    """Single-element RFC 9497 VOPRF evaluation response."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    protocol_version: str
    deployment_id: str
    voprf_key_version: int = Field(ge=1, le=2**32 - 1)
    voprf_mode: str
    voprf_ciphersuite: str
    linkage_encoding_version: int
    evaluated_element: str
    proof: str

    @field_validator("deployment_id")
    @classmethod
    def validate_deployment_id(cls, value: str) -> str:
        return _canonical_deployment_id(value)


class OmneumErrorResponse(BaseModel):
    """Stable structured tool failure."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    message: str
    omneum_code: OmneumCode


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )


class Assertion(_StrictModel):
    source_id: str = Field(description=(
        "Opaque source linkage token: canonical unpadded base64url encoding of "
        "64 bytes, exactly 86 characters. Use the Omneum SDK to generate and "
        "retain its local mapping."
    ))
    attribute_id: str = Field(description=(
        "Opaque linkage token identifying the entity-attribute being asserted: "
        "canonical unpadded base64url encoding of 64 bytes, exactly 86 characters."
    ))
    claim_id: str = Field(description=(
        "Opaque linkage token identifying a claim value for its attribute: "
        "canonical unpadded base64url encoding of 64 bytes, exactly 86 characters."
    ))


class SourcePair(_StrictModel):
    source_a_id: str = Field(description=(
        "Source linkage token present in assertions, lexicographically smaller "
        "than source_b_id. Canonical unpadded base64url encoding of 64 bytes "
        "(86 characters)."
    ))
    source_b_id: str = Field(description=(
        "Distinct source linkage token present in assertions, lexicographically "
        "larger than source_a_id. Canonical unpadded base64url encoding of "
        "64 bytes (86 characters)."
    ))
    dependency: float = Field(description=(
        "Caller-supplied pairwise evidence-dependency score, finite and within "
        "[0,1]: zero represents no modeled dependency; one represents maximal "
        "dependency. This does not certify exact equivalence."
    ))
    weighted_signal_coverage: float = Field(description=(
        "Caller-supplied weighted coverage of observable dependency signals, "
        "finite and within [0,1]. Used for coverage diagnostics, not as an "
        "additional inference weight."
    ))
    exact_equivalence: bool = Field(
        default=False,
        description=(
            "Explicit certification of identical evidence; not ordinary derivation. "
            "True links form transitive equivalence groups. Group members must "
            "have identical claim profiles and uniform dependencies to other groups."
        ),
    )


class EvaluateAssertionRequest(_StrictModel):
    protocol_version: str = Field(description="Omneum protocol version. Must be v1.")
    deployment_id: str = Field(description=(
        "Deployment identifier from the initialized client configuration or ping. "
        "Must be a canonical lowercase urn:uuid:… value matching this server."
    ))
    voprf_key_version: int = Field(
        ge=1,
        le=2**32 - 1,
        description="VOPRF key version matching this deployment's configured key version.",
    )
    voprf_mode: str = Field(description="VOPRF mode. Must be voprf.")
    voprf_ciphersuite: str = Field(description=(
        "VOPRF ciphersuite. Must be ristretto255-SHA512."
    ))
    linkage_encoding_version: int = Field(description=(
        "Omneum linkage encoding version. Must be 1."
    ))
    assertions: list[Assertion] = Field(description=(
        "1-4096 unique assertion triples, sorted lexicographically by "
        "(source_id, attribute_id, claim_id). Each source may assert at most one "
        "claim per attribute; each claim belongs to exactly one attribute. "
        "At most 64 distinct sources, 2048 attributes, and 4096 claims. "
        "The sum of k*(k-1) across attributes, where k is the attribute's "
        "distinct claim count, must not exceed 16384 conflicting-claim entries."
    ))
    source_pairs: list[SourcePair] = Field(description=(
        "Complete unordered source-pair matrix: exactly n*(n-1)/2 entries "
        "for the n distinct sources in assertions, at most 2016 entries. "
        "Sort lexicographically by (source_a_id, source_b_id); use an empty "
        "array for one source. No duplicate, diagonal, reversed, or unknown-source pairs."
    ))

    @field_validator("deployment_id")
    @classmethod
    def validate_deployment_id(cls, value: str) -> str:
        return _canonical_deployment_id(value)


class SourceReliability(_StrictModel):
    source_id: str
    reliability: float = Field(ge=0, allow_inf_nan=False)


class ConflictingClaim(_StrictModel):
    claim_id: str
    support: float = Field(ge=0, allow_inf_nan=False)


class SupportingSource(_StrictModel):
    source_id: str
    independence: float = Field(
        ge=0,
        le=1,
        allow_inf_nan=False,
    )
    contribution: float = Field(ge=0, allow_inf_nan=False)


class ClaimSupport(_StrictModel):
    attribute_id: str
    claim_id: str
    support: float = Field(ge=0, allow_inf_nan=False)
    agreement_weight: float = Field(
        ge=0,
        le=1,
        allow_inf_nan=False,
    )
    is_attribute_max_support: bool
    supporting_source_count: int = Field(ge=1)
    estimated_independent_support_count: float = Field(
        ge=1,
        allow_inf_nan=False,
    )
    dependency_signal_coverage: float | None = Field(
        ge=0,
        le=1,
        allow_inf_nan=False,
    )
    supporting_sources: list[SupportingSource]
    conflicting_claims: list[ConflictingClaim]


class Summary(_StrictModel):
    source_count: int = Field(ge=1, le=64)
    claim_count: int = Field(ge=1, le=4096)
    assertion_count: int = Field(ge=1, le=4096)


class Metadata(_StrictModel):
    algorithm_version: str
    iterations: int = Field(ge=1, le=1000)
    converged: bool
    convergence_tolerance: float = Field(
        ge=0,
        allow_inf_nan=False,
    )
    convergence_delta: float = Field(
        ge=0,
        allow_inf_nan=False,
    )


class EvaluateAssertionResponse(_StrictModel):
    protocol_version: str
    deployment_id: str
    voprf_key_version: int = Field(ge=1, le=2**32 - 1)
    voprf_mode: str
    voprf_ciphersuite: str
    linkage_encoding_version: int
    evaluation_latency_ms: float | None = Field(
        default=None, ge=0, allow_inf_nan=False,
        description=(
            "Server evaluation elapsed milliseconds, including graph validation, "
            "queue wait, inference and response validation; excludes SDK dependency "
            "estimation, linkage, transport, persistence and reconstruction."
        ),
    )
    summary: Summary
    source_reliability: list[SourceReliability]
    claim_support: list[ClaimSupport]
    metadata: Metadata

    @field_validator("deployment_id")
    @classmethod
    def validate_deployment_id(cls, value: str) -> str:
        return _canonical_deployment_id(value)


class PingResponse(BaseModel):

    status: str

    protocol_version: str
    algorithm_version: str
    deployment_id: str
    voprf_key_version: int
    voprf_mode: str
    voprf_ciphersuite: str
    linkage_encoding_version: int
    configuration_fingerprint: str
