import uuid

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)


class EvaluateVOPRFRequest(BaseModel):
    """Single-element RFC 9497 VOPRF evaluation request."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    protocol_version: str
    deployment_id: str
    voprf_key_version: int = Field(
        ge=1,
        le=2**32 - 1,
    )
    voprf_mode: str
    voprf_ciphersuite: str
    linkage_encoding_version: int
    blinded_element: str

    @field_validator("deployment_id")
    @classmethod
    def validate_deployment_id(cls, value: str) -> str:
        prefix = "urn:uuid:"
        if not value.startswith(prefix):
            raise ValueError(
                "deployment_id must be a canonical UUID URN"
            )
        try:
            parsed = uuid.UUID(value[len(prefix):])
        except ValueError:
            raise ValueError(
                "deployment_id must be a canonical UUID URN"
            ) from None
        if value != f"{prefix}{parsed}":
            raise ValueError(
                "deployment_id must be a canonical UUID URN"
            )
        return value


class EvaluateVOPRFResponse(BaseModel):
    """Single-element RFC 9497 VOPRF evaluation response."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    protocol_version: str
    deployment_id: str
    voprf_key_version: int
    voprf_mode: str
    voprf_ciphersuite: str
    linkage_encoding_version: int
    evaluated_element: str
    proof: str


class VerityErrorResponse(BaseModel):
    """Stable structured tool failure."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    message: str
    verity_code: str


# Request Models

class Assertion(BaseModel):
    """
    A protocol assertion submitted to a Verity deployment.
    """

    source_id: str = Field(
        ...,
        description="Opaque source identifier."
    )

    attribute_id: str = Field(
        ...,
        description="Opaque attribute linkage identifier."
    )

    claim_id: str = Field(
        ...,
        description="Opaque claim linkage identifier."
    )


class InferCredibilityRequest(BaseModel):
    """
    infer_credibility request.
    """

    assertions: list[Assertion]


class TraceClaimRequest(BaseModel):
    """
    trace_claim request.
    """

    claim_id: str

# Shared Response Models

class SourceCredibility(BaseModel):

    source_id: str
    credibility: float


class ConflictingClaim(BaseModel):

    claim_id: str
    support: float


class ClaimSupport(BaseModel):

    attribute_id: str
    claim_id: str

    support: float

    is_attribute_max_support: bool

    conflicting_claims: list[ConflictingClaim]


class Summary(BaseModel):

    source_count: int
    claim_count: int
    assertion_count: int


class Metadata(BaseModel):

    algorithm_version: str

    iterations: int
    converged: bool

    computation_time_ms: int

# Tool Responses

class InferCredibilityResponse(BaseModel):

    summary: Summary

    source_credibility: list[SourceCredibility]

    claim_support: list[ClaimSupport]

    metadata: Metadata


class TraceClaimResponse(BaseModel):

    attribute_id: str

    claim_id: str

    support: float

    is_attribute_max_support: bool

    supporting_sources: list[SourceCredibility]

    conflicting_claims: list[ConflictingClaim]


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
