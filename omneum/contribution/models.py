from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, revalidate_instances="always")


class ContributionSource(_StrictModel):
    source_id: str
    source_token: str
    source_kind: Literal[
        "web_document", "web_publisher", "internal_resource",
        "internal_service", "database", "url",
    ]
    key_version: int = Field(ge=1, le=2**32 - 1)


class ContributionClaim(_StrictModel):
    claim_id: str
    claim_token: str
    key_version: int = Field(ge=1, le=2**32 - 1)


class ContributionObservation(_StrictModel):
    source_id: str
    claim_id: str
    observation_type: Literal["assertion"] = "assertion"
    observed_bucket: str | None = None


class ContributionSourceScore(_StrictModel):
    source_id: str
    reliability: float = Field(ge=0, allow_inf_nan=False)
    contribution_score: float | None = Field(
        default=None,
        ge=0,
        allow_inf_nan=False,
    )


class ContributionClaimScore(_StrictModel):
    claim_id: str
    support: float = Field(ge=0, allow_inf_nan=False)
    supporting_source_count: int = Field(ge=1)
    estimated_independent_support_count: float = Field(
        ge=1,
        allow_inf_nan=False,
    )
    dependency_cluster_count: int | None = Field(
        default=None,
        ge=0,
    )
    dependency_signal_coverage: float | None = Field(
        default=None,
        ge=0,
        le=1,
        allow_inf_nan=False,
    )


class ContributionDependency(_StrictModel):
    source_low_id: str
    source_high_id: str
    dependency_score: float = Field(
        ge=0,
        le=1,
        allow_inf_nan=False,
    )

    upstream_signal: float | None = Field(
        default=None, ge=0, le=1, allow_inf_nan=False
    )
    citation_signal: float | None = Field(
        default=None, ge=0, le=1, allow_inf_nan=False
    )
    assertion_lineage_signal: float | None = Field(
        default=None, ge=0, le=1, allow_inf_nan=False
    )
    ownership_signal: float | None = Field(
        default=None, ge=0, le=1, allow_inf_nan=False
    )
    temporal_signal: float | None = Field(
        default=None, ge=0, le=1, allow_inf_nan=False
    )
    graph_signal: float | None = Field(
        default=None, ge=0, le=1, allow_inf_nan=False
    )
    retrieval_signal: float | None = Field(
        default=None, ge=0, le=1, allow_inf_nan=False
    )

    signal_coverage: float | None = Field(
        default=None,
        ge=0,
        le=1,
        allow_inf_nan=False,
    )

    # Component names are protocol fields, never application metadata.
    signal_components: dict[Literal[
        "upstream", "citation", "assertion_lineage", "ownership",
        "temporal", "graph", "retrieval",
    ], float] = Field(default_factory=dict)

    # Directional structural evidence. This is deliberately typed rather
    # than accepting arbitrary metadata.
    source_low_upstream_of_source_high: bool = False
    source_high_upstream_of_source_low: bool = False
    source_low_cites_source_high: bool = False
    source_high_cites_source_low: bool = False
    source_low_parent_count: int = Field(default=0, ge=0)
    source_high_parent_count: int = Field(default=0, ge=0)
    same_owner: bool = False
    matching_claim_count: int = Field(default=0, ge=0)
    qualifying_time_deltas_seconds: tuple[float, ...] = ()


class EvaluationContribution(_StrictModel):
    schema_version: Literal["1"] = "1"
    idempotency_key: str

    evaluator_version: str
    estimator_version: str

    sources: tuple[ContributionSource, ...]
    claims: tuple[ContributionClaim, ...]
    observations: tuple[ContributionObservation, ...]
    source_scores: tuple[ContributionSourceScore, ...]
    claim_scores: tuple[ContributionClaimScore, ...]
    dependencies: tuple[ContributionDependency, ...]
