from pydantic import BaseModel, Field


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