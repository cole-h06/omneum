from __future__ import annotations

import asyncio
import math
import os
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol

from mcp import ClientSession, StdioServerParameters, stdio_client
from mcp.types import CallToolResult
from pydantic import ValidationError

from .base64url import decode_unpadded, encode_unpadded
from .canonicalization import (
    canonicalize_attribute,
    canonicalize_entity,
    canonicalize_source,
    canonicalize_value,
)
from .config import (
    PROTOCOL_VERSION,
    VOPRF_MODE,
    ConfigurationError,
    load_config_file,
)
from .dependency import (
    DependencyCluster,
    DependencyEstimatorConfig,
    PairwiseDependencyResult,
    estimate_dependencies,
)
from .engine_graph import AssertionTriple, SourcePair, build_graph
from .inference import (
    ALGORITHM_VERSION,
    CONVERGENCE_TOLERANCE,
    infer,
)
from .information import (
    Claim,
    Observation,
    Retrieval,
    Source,
    SourceReference,
)
from .linkage import (
    ENCODING_VERSION,
    LinkageBlindResult,
    LinkageClient,
    LinkagePurpose,
)
from .models import (
    Assertion as RequestAssertion,
    EvaluateAssertionRequest,
    EvaluateAssertionResponse,
    EvaluateVOPRFRequest,
    EvaluateVOPRFResponse,
    SourcePair as RequestSourcePair,
    OmneumErrorResponse,
)
from .oprf import (
    CIPHERSUITE,
    ELEMENT_LENGTH,
    OUTPUT_LENGTH,
    PROOF_LENGTH,
    OPRFError,
    VOPRFClient,
    VOPRFEvaluation,
)
from .serialization import serialize_claim, serialize_source


class OmneumClientError(Exception):
    """Base class for high-level Omneum client failures."""


class OmneumClientConfigurationError(OmneumClientError, ValueError):
    """Authenticated pinned client configuration is invalid."""


class EvaluationTransportError(OmneumClientError):
    """The evaluator transport failed."""

    def __init__(self, *, uncertain: bool) -> None:
        super().__init__("VOPRF evaluation transport failed.")
        self.uncertain = uncertain


class EvaluationRejectedError(OmneumClientError):
    """The evaluator returned a valid version-1 Omneum failure."""

    def __init__(self, omneum_code: str) -> None:
        super().__init__("VOPRF evaluation was rejected.")
        self.omneum_code = omneum_code


class EvaluationResponseError(OmneumClientError):
    """The evaluator response was malformed or inconsistent."""


class EvaluationVerificationError(OmneumClientError):
    """The VOPRF proof or finalization result was invalid."""


class AssertionEvaluationTransportError(OmneumClientError):
    def __init__(self, *, uncertain: bool) -> None:
        super().__init__("Assertion evaluation transport failed.")
        self.uncertain = uncertain


class AssertionEvaluationRejectedError(OmneumClientError):
    def __init__(self, omneum_code: str) -> None:
        super().__init__("Assertion evaluation was rejected.")
        self.omneum_code = omneum_code


class AssertionEvaluationResponseError(OmneumClientError):
    """The assertion-evaluation response was malformed or inconsistent."""


class AssertionEvaluationMappingError(OmneumClientError):
    """The assertion-evaluation response could not be mapped locally."""


def _exact(value, expected, name):
    if type(value) is not expected:
        raise TypeError(f"{name} must be a {expected.__name__}")


def _result_number(value, name, *, minimum=None, maximum=None):
    if type(value) is not float:
        raise TypeError(f"{name} must be a float")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} is below its minimum")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} is above its maximum")


def _tuple_of(value, expected, name):
    if type(value) is not tuple:
        raise TypeError(f"{name} must be a tuple")
    if any(type(item) is not expected for item in value):
        raise TypeError(f"{name} contains an invalid value")


def _canonical_source_identity(value):
    return (
        value.kind,
        canonicalize_source(
            value.kind,
            value.identifier,
        ),
    )


@dataclass(frozen=True, slots=True)
class SourceEvaluation:
    source: Source = field(repr=False)
    reliability: float

    def __post_init__(self):
        _exact(self.source, Source, "source")
        _result_number(
            self.reliability,
            "reliability",
            minimum=0.0,
            maximum=1.0,
        )


@dataclass(frozen=True, slots=True)
class SupportingSourceResult:
    source: Source = field(repr=False)
    independence: float
    contribution: float

    def __post_init__(self):
        _exact(self.source, Source, "source")
        _result_number(
            self.independence,
            "independence",
            minimum=0.0,
            maximum=1.0,
        )
        _result_number(
            self.contribution,
            "contribution",
            minimum=0.0,
        )


@dataclass(frozen=True, slots=True)
class ConflictingClaimResult:
    claim: Claim = field(repr=False)
    support: float

    def __post_init__(self):
        _exact(self.claim, Claim, "claim")
        _result_number(
            self.support,
            "support",
            minimum=0.0,
        )


@dataclass(frozen=True, slots=True)
class ClaimSupportResult:
    claim: Claim = field(repr=False)
    support: float
    agreement_weight: float
    is_attribute_max_support: bool
    supporting_source_count: int
    estimated_independent_support_count: float
    dependency_confidence: float | None
    supporting_sources: tuple[SupportingSourceResult, ...]
    conflicting_claims: tuple[ConflictingClaimResult, ...]
    dependency_clusters: tuple[DependencyCluster, ...] | None

    def __post_init__(self):
        _exact(self.claim, Claim, "claim")

        _result_number(
            self.support,
            "support",
            minimum=0.0,
        )

        _result_number(
            self.agreement_weight,
            "agreement_weight",
            minimum=0.0,
            maximum=1.0,
        )

        if type(self.is_attribute_max_support) is not bool:
            raise TypeError(
                "is_attribute_max_support must be a bool"
            )

        if type(self.supporting_source_count) is not int:
            raise TypeError(
                "supporting_source_count must be an integer"
            )

        if self.supporting_source_count < 1:
            raise ValueError(
                "supporting_source_count must be positive"
            )

        _result_number(
            self.estimated_independent_support_count,
            "estimated_independent_support_count",
            minimum=1.0,
            maximum=float(self.supporting_source_count),
        )

        if self.supporting_source_count == 1:
            if self.dependency_confidence is not None:
                raise ValueError(
                    "singleton dependency_confidence must be None"
                )
        else:
            _result_number(
                self.dependency_confidence,
                "dependency_confidence",
                minimum=0.0,
                maximum=1.0,
            )

        _tuple_of(
            self.supporting_sources,
            SupportingSourceResult,
            "supporting_sources",
        )

        if (
            len(self.supporting_sources)
            != self.supporting_source_count
        ):
            raise ValueError(
                "supporting source count is inconsistent"
            )

        supporting_identities = tuple(
            _canonical_source_identity(item.source)
            for item in self.supporting_sources
        )

        if (
            len(set(supporting_identities))
            != len(supporting_identities)
        ):
            raise ValueError(
                "supporting sources must be unique"
            )

        if self.supporting_source_count == 1 and (
            self.estimated_independent_support_count != 1.0
            or self.supporting_sources[0].independence != 1.0
        ):
            raise ValueError(
                "singleton support telemetry is inconsistent"
            )

        _tuple_of(
            self.conflicting_claims,
            ConflictingClaimResult,
            "conflicting_claims",
        )

        if (
            len(
                {
                    item.claim
                    for item in self.conflicting_claims
                }
            )
            != len(self.conflicting_claims)
        ):
            raise ValueError(
                "conflicting claims must be unique"
            )

        if self.dependency_clusters is not None:
            _tuple_of(
                self.dependency_clusters,
                DependencyCluster,
                "dependency_clusters",
            )

            supporting = set(supporting_identities)
            clustered = []

            for cluster in self.dependency_clusters:
                clustered.extend(
                    _canonical_source_identity(source)
                    for source in cluster.sources
                )

            if len(set(clustered)) != len(clustered):
                raise ValueError(
                    "dependency clusters must not overlap"
                )

            if set(clustered) != supporting:
                raise ValueError(
                    "dependency clusters must partition "
                    "supporting sources"
                )

            cluster_order = tuple(
                serialize_source(
                    *_canonical_source_identity(
                        cluster.sources[0]
                    )
                )
                for cluster in self.dependency_clusters
            )

            if cluster_order != tuple(
                sorted(cluster_order)
            ):
                raise ValueError(
                    "dependency clusters must be "
                    "canonically ordered"
                )


@dataclass(frozen=True, slots=True)
class ConvergenceMetadata:
    algorithm_version: str
    iterations: int
    converged: bool
    convergence_tolerance: float
    convergence_delta: float

    def __post_init__(self):
        if type(self.algorithm_version) is not str:
            raise TypeError(
                "algorithm_version must be a string"
            )

        if self.algorithm_version != ALGORITHM_VERSION:
            raise ValueError(
                "algorithm_version is unsupported"
            )

        if type(self.iterations) is not int:
            raise TypeError(
                "iterations must be an integer"
            )

        if not 1 <= self.iterations <= 1000:
            raise ValueError(
                "iterations is outside the supported range"
            )

        if type(self.converged) is not bool:
            raise TypeError(
                "converged must be a bool"
            )

        if not self.converged:
            raise ValueError(
                "assertion evaluation must be converged"
            )

        _result_number(
            self.convergence_tolerance,
            "convergence_tolerance",
            minimum=0.0,
        )

        if (
            self.convergence_tolerance
            != CONVERGENCE_TOLERANCE
        ):
            raise ValueError(
                "convergence_tolerance is unsupported"
            )

        _result_number(
            self.convergence_delta,
            "convergence_delta",
            minimum=0.0,
        )

        if (
            self.convergence_delta
            >= self.convergence_tolerance
        ):
            raise ValueError(
                "convergence_delta is not converged"
            )


@dataclass(frozen=True, slots=True)
class AssertionEvaluation:
    source_reliability: tuple[SourceEvaluation, ...]
    claim_support: tuple[ClaimSupportResult, ...]
    pairwise_dependencies: tuple[
        PairwiseDependencyResult,
        ...,
    ]
    convergence: ConvergenceMetadata
    dependency_cluster_threshold: float | None = field(
        repr=False
    )

    def __post_init__(self):
        _tuple_of(
            self.source_reliability,
            SourceEvaluation,
            "source_reliability",
        )

        if not self.source_reliability:
            raise ValueError(
                "source_reliability must not be empty"
            )

        source_identities = tuple(
            _canonical_source_identity(item.source)
            for item in self.source_reliability
        )

        if (
            len(set(source_identities))
            != len(source_identities)
        ):
            raise ValueError(
                "source reliability entries must be unique"
            )

        _tuple_of(
            self.claim_support,
            ClaimSupportResult,
            "claim_support",
        )

        if not self.claim_support:
            raise ValueError(
                "claim_support must not be empty"
            )

        if (
            len(
                {
                    item.claim
                    for item in self.claim_support
                }
            )
            != len(self.claim_support)
        ):
            raise ValueError(
                "claim support entries must be unique"
            )

        _tuple_of(
            self.pairwise_dependencies,
            PairwiseDependencyResult,
            "pairwise_dependencies",
        )

        ordered_sources = tuple(
            sorted(
                source_identities,
                key=lambda source: serialize_source(
                    *source
                ),
            )
        )

        expected_pairs = tuple(
            (source_a, source_b)
            for index, source_a in enumerate(
                ordered_sources
            )
            for source_b in ordered_sources[
                index + 1 :
            ]
        )

        actual_pairs = tuple(
            (
                _canonical_source_identity(
                    pair.source_a
                ),
                _canonical_source_identity(
                    pair.source_b
                ),
            )
            for pair in self.pairwise_dependencies
        )

        if actual_pairs != expected_pairs:
            raise ValueError(
                "pairwise dependency matrix is incomplete"
            )

        _exact(
            self.convergence,
            ConvergenceMetadata,
            "convergence",
        )

        if self.dependency_cluster_threshold is not None:
            _result_number(
                self.dependency_cluster_threshold,
                "dependency_cluster_threshold",
                minimum=0.0,
                maximum=1.0,
            )

        for claim in self.claim_support:
            clusters = claim.dependency_clusters

            if self.dependency_cluster_threshold is None:
                if clusters is not None:
                    raise ValueError(
                        "dependency clusters require "
                        "a threshold"
                    )
            elif clusters is None or any(
                cluster.threshold
                != self.dependency_cluster_threshold
                for cluster in clusters
            ):
                raise ValueError(
                    "dependency cluster threshold "
                    "is inconsistent"
                )


@dataclass(frozen=True, slots=True)
class OmneumClientConfig:
    """Authenticated deployment metadata and VOPRF public-key pin."""

    deployment_id: str = field(repr=False)
    voprf_key_version: int = field(repr=False)
    voprf_mode: str = field(repr=False)
    voprf_ciphersuite: str = field(repr=False)
    linkage_encoding_version: int = field(repr=False)
    voprf_public_key: bytes = field(repr=False)

    def __post_init__(self) -> None:
        _validate_deployment_id(self.deployment_id)

        if (
            type(self.voprf_key_version) is not int
            or not 1
            <= self.voprf_key_version
            <= 2**32 - 1
        ):
            raise OmneumClientConfigurationError(
                "VOPRF key version is invalid."
            )

        if self.voprf_mode != VOPRF_MODE:
            raise OmneumClientConfigurationError(
                "VOPRF mode is unsupported."
            )

        if self.voprf_ciphersuite != CIPHERSUITE:
            raise OmneumClientConfigurationError(
                "VOPRF ciphersuite is unsupported."
            )

        if (
            self.linkage_encoding_version
            != ENCODING_VERSION
        ):
            raise OmneumClientConfigurationError(
                "Linkage encoding version is unsupported."
            )

        if (
            type(self.voprf_public_key) is not bytes
            or len(self.voprf_public_key)
            != ELEMENT_LENGTH
        ):
            raise OmneumClientConfigurationError(
                "VOPRF public-key pin is invalid."
            )

    @classmethod
    def from_local_deployment(cls) -> OmneumClientConfig:
        config = load_config_file()

        return cls.from_base64url(
            deployment_id=config["deployment_id"],
            voprf_key_version=config["voprf_key_version"],
            voprf_mode=VOPRF_MODE,
            voprf_ciphersuite=CIPHERSUITE,
            linkage_encoding_version=ENCODING_VERSION,
            voprf_public_key=config["voprf_public_key"],
        )

    @classmethod
    def from_base64url(
        cls,
        *,
        deployment_id: str,
        voprf_key_version: int,
        voprf_mode: str,
        voprf_ciphersuite: str,
        linkage_encoding_version: int,
        voprf_public_key: str,
    ) -> OmneumClientConfig:
        try:
            public_key = decode_unpadded(
                voprf_public_key,
                expected_length=ELEMENT_LENGTH,
            )
        except ValueError:
            raise OmneumClientConfigurationError(
                "VOPRF public-key pin is invalid."
            ) from None

        return cls(
            deployment_id=deployment_id,
            voprf_key_version=voprf_key_version,
            voprf_mode=voprf_mode,
            voprf_ciphersuite=voprf_ciphersuite,
            linkage_encoding_version=(
                linkage_encoding_version
            ),
            voprf_public_key=public_key,
        )


@dataclass(frozen=True, slots=True)
class LinkageToken:
    deployment_id: str = field(repr=False)
    voprf_key_version: int = field(repr=False)
    voprf_mode: str = field(repr=False)
    voprf_ciphersuite: str = field(repr=False)
    linkage_encoding_version: int = field(repr=False)
    purpose: LinkagePurpose = field(repr=False)
    value: bytes = field(repr=False)

    def __post_init__(self) -> None:
        _validate_deployment_id(self.deployment_id)

        if (
            type(self.voprf_key_version) is not int
            or not 1
            <= self.voprf_key_version
            <= 2**32 - 1
        ):
            raise ValueError(
                "VOPRF key version is invalid"
            )

        if (
            type(self.voprf_mode) is not str
            or self.voprf_mode != VOPRF_MODE
        ):
            raise ValueError(
                "VOPRF mode is invalid"
            )

        if (
            type(self.voprf_ciphersuite) is not str
            or self.voprf_ciphersuite != CIPHERSUITE
        ):
            raise ValueError(
                "VOPRF ciphersuite is invalid"
            )

        if (
            type(self.linkage_encoding_version)
            is not int
            or self.linkage_encoding_version
            != ENCODING_VERSION
        ):
            raise ValueError(
                "linkage encoding version is invalid"
            )

        if type(self.purpose) is not LinkagePurpose:
            raise TypeError(
                "purpose must be a LinkagePurpose"
            )

        if (
            type(self.value) is not bytes
            or len(self.value) != OUTPUT_LENGTH
        ):
            raise ValueError(
                "linkage token must be 64 bytes"
            )

    def to_base64url(self) -> str:
        return encode_unpadded(
            self.value,
            expected_length=OUTPUT_LENGTH,
        )


class _OmneumEvaluator(Protocol):
    async def evaluate_voprf(
        self,
        request: EvaluateVOPRFRequest,
    ) -> CallToolResult:
        ...

    async def evaluate_assertion(
        self,
        request: EvaluateAssertionRequest,
    ) -> CallToolResult:
        ...


class OmneumClient:
    """Async client for local, pinned Omneum linkage evaluation."""

    def __init__(
        self,
        config: OmneumClientConfig,
        evaluator: _OmneumEvaluator,
        *,
        assertion_evaluation_available: bool | None = None,
    ) -> None:
        if type(config) is not OmneumClientConfig:
            raise TypeError(
                "config must be a OmneumClientConfig"
            )

        if not callable(
            getattr(
                evaluator,
                "evaluate_voprf",
                None,
            )
        ):
            raise TypeError(
                "evaluator must implement the "
                "evaluator protocol"
            )

        try:
            oprf_client = VOPRFClient(
                config.voprf_public_key
            )
        except OPRFError:
            raise OmneumClientConfigurationError(
                "VOPRF public-key pin is invalid."
            ) from None

        self._config = config
        self._evaluator = evaluator

        self._assertion_evaluation_available = (
            callable(
                getattr(
                    evaluator,
                    "evaluate_assertion",
                    None,
                )
            )
            if assertion_evaluation_available is None
            else assertion_evaluation_available
        )

        self._linkage = LinkageClient(oprf_client)

    async def link_source(
        self,
        kind: str,
        identifier: str,
    ) -> LinkageToken:
        canonical = canonicalize_source(
            kind,
            identifier,
        )

        return await self._evaluate(
            self._linkage.blind_source(
                kind,
                canonical,
            )
        )

    async def link_attribute(
        self,
        entity_namespace: str,
        entity: str,
        attribute: str,
    ) -> LinkageToken:
        canonical_entity = canonicalize_entity(
            entity_namespace,
            entity,
        )

        canonical_attribute = canonicalize_attribute(
            attribute
        )

        return await self._evaluate(
            self._linkage.blind_attribute(
                entity_namespace,
                canonical_entity,
                canonical_attribute,
            )
        )

    async def link_claim(
        self,
        entity_namespace: str,
        entity: str,
        attribute: str,
        value: Any,
    ) -> LinkageToken:
        canonical_entity = canonicalize_entity(
            entity_namespace,
            entity,
        )

        canonical_attribute = canonicalize_attribute(
            attribute
        )

        canonical_value = canonicalize_value(value)

        return await self._evaluate(
            self._linkage.blind_claim(
                entity_namespace,
                canonical_entity,
                canonical_attribute,
                canonical_value,
            )
        )

    async def evaluate_assertion(
        self,
        observations: Sequence[Observation],
        *,
        estimator: DependencyEstimatorConfig,
    ) -> AssertionEvaluation:
        if not self._assertion_evaluation_available:
            raise AssertionEvaluationResponseError(
                "The evaluate_assertion tool is unavailable."
            )

        values = tuple(observations)

        if any(
            type(value) is not Observation
            for value in values
        ):
            raise TypeError(
                "observations must contain "
                "Observation values"
            )

        values = _snapshot_observations(values)

        sources_by_key = {}

        for value in values:
            key = (
                value.source.kind,
                canonicalize_source(
                    value.source.kind,
                    value.source.identifier,
                ),
            )

            previous = sources_by_key.get(key)

            if (
                previous is not None
                and previous.owner_id
                != value.source.owner_id
            ):
                from .dependency import (
                    InformationGraphError,
                )

                raise InformationGraphError(
                    "canonical source has "
                    "conflicting owners"
                )

            sources_by_key.setdefault(
                key,
                value.source,
            )

        pairs, _ = estimate_dependencies(
            tuple(sources_by_key.values()),
            values,
            estimator,
        )

        source_tokens = {}
        source_objects = {}
        used_tokens = set()

        for key in sorted(sources_by_key):
            item = sources_by_key[key]

            token = await self.link_source(
                item.kind,
                item.identifier,
            )

            self._check_token(
                token,
                "source",
            )

            encoded = token.to_base64url()

            if encoded in used_tokens:
                raise AssertionEvaluationMappingError(
                    "Linkage token mapping is invalid."
                )

            used_tokens.add(encoded)
            source_tokens[key] = encoded
            source_objects[encoded] = item

        attribute_tokens = {}
        claim_tokens = {}
        claim_objects = {}
        canonical_rows = []

        for value in values:
            source_key = (
                value.source.kind,
                canonicalize_source(
                    value.source.kind,
                    value.source.identifier,
                ),
            )

            claim = value.claim

            entity = canonicalize_entity(
                claim.entity_namespace,
                claim.entity,
            )

            attribute = canonicalize_attribute(
                claim.attribute
            )

            claim_value = canonicalize_value(
                claim.value
            )

            attribute_key = (
                claim.entity_namespace,
                entity,
                attribute,
            )

            claim_key = serialize_claim(
                *attribute_key,
                claim_value,
            )

            canonical_rows.append(
                (
                    source_key,
                    attribute_key,
                    claim_key,
                )
            )

            if (
                attribute_key
                not in attribute_tokens
            ):
                token = await self.link_attribute(
                    *attribute_key
                )

                self._check_token(
                    token,
                    "attribute",
                )

                encoded = token.to_base64url()

                if encoded in used_tokens:
                    raise AssertionEvaluationMappingError(
                        "Linkage token mapping "
                        "is invalid."
                    )

                used_tokens.add(encoded)

                attribute_tokens[
                    attribute_key
                ] = encoded

            if claim_key not in claim_tokens:
                token = await self.link_claim(
                    claim.entity_namespace,
                    entity,
                    attribute,
                    claim_value,
                )

                self._check_token(
                    token,
                    "claim",
                )

                encoded = token.to_base64url()

                if encoded in used_tokens:
                    raise AssertionEvaluationMappingError(
                        "Linkage token mapping "
                        "is invalid."
                    )

                used_tokens.add(encoded)
                claim_tokens[claim_key] = encoded

                claim_objects[encoded] = Claim(
                    claim.entity_namespace,
                    entity,
                    attribute,
                    claim_value,
                )

        assertions = tuple(
            sorted(
                [
                    RequestAssertion(
                        source_id=(
                            source_tokens[
                                source_key
                            ]
                        ),
                        attribute_id=(
                            attribute_tokens[
                                attribute_key
                            ]
                        ),
                        claim_id=(
                            claim_tokens[
                                claim_key
                            ]
                        ),
                    )
                    for (
                        source_key,
                        attribute_key,
                        claim_key,
                    ) in canonical_rows
                ],
                key=lambda item: (
                    item.source_id,
                    item.attribute_id,
                    item.claim_id,
                ),
            )
        )

        pair_values = []

        for pair in pairs:
            a = source_tokens[
                (
                    pair.source_a.kind,
                    pair.source_a.identifier,
                )
            ]

            b = source_tokens[
                (
                    pair.source_b.kind,
                    pair.source_b.identifier,
                )
            ]

            if a > b:
                a, b = b, a

            pair_values.append(
                RequestSourcePair(
                    source_a_id=a,
                    source_b_id=b,
                    dependency=pair.dependency,
                    weighted_signal_coverage=(
                        pair.weighted_signal_coverage
                    ),
                )
            )

        pair_values.sort(
            key=lambda item: (
                item.source_a_id,
                item.source_b_id,
            )
        )

        request = EvaluateAssertionRequest(
            protocol_version=PROTOCOL_VERSION,
            deployment_id=(
                self._config.deployment_id
            ),
            voprf_key_version=(
                self._config.voprf_key_version
            ),
            voprf_mode=self._config.voprf_mode,
            voprf_ciphersuite=(
                self._config.voprf_ciphersuite
            ),
            linkage_encoding_version=(
                self._config.linkage_encoding_version
            ),
            assertions=list(assertions),
            source_pairs=pair_values,
        )

        try:
            result = (
                await self._evaluator.evaluate_assertion(
                    request
                )
            )
        except asyncio.CancelledError:
            raise
        except AssertionEvaluationTransportError:
            raise
        except Exception:
            raise AssertionEvaluationTransportError(
                uncertain=True
            ) from None

        response = (
            self._validate_assertion_response(
                result
            )
        )

        _validate_mapping(
            response,
            set(source_objects),
            set(attribute_tokens.values()),
            set(claim_objects),
        )

        expected_graph = build_graph(
            tuple(
                AssertionTriple(
                    item.source_id,
                    item.attribute_id,
                    item.claim_id,
                )
                for item in assertions
            ),
            tuple(
                SourcePair(
                    item.source_a_id,
                    item.source_b_id,
                    item.dependency,
                    item.weighted_signal_coverage,
                )
                for item in pair_values
            ),
        )

        expected = infer(expected_graph)

        _compare_assertion_evaluation(
            response,
            expected,
        )

        try:
            return _map_assertion_evaluation(
                response,
                source_objects,
                claim_objects,
                pairs,
                estimator.dependency_cluster_threshold,
            )
        except (KeyError, ValueError, TypeError):
            raise AssertionEvaluationMappingError(
                "Assertion-evaluation response "
                "could not be mapped."
            ) from None

    def _check_token(
        self,
        token: LinkageToken,
        purpose: str,
    ) -> None:
        comparisons = (
            token.deployment_id
            == self._config.deployment_id,
            token.voprf_key_version
            == self._config.voprf_key_version,
            token.voprf_mode
            == self._config.voprf_mode,
            token.voprf_ciphersuite
            == self._config.voprf_ciphersuite,
            token.linkage_encoding_version
            == self._config.linkage_encoding_version,
            token.purpose
            == {
                "source": LinkagePurpose.SOURCE,
                "attribute": LinkagePurpose.ATTRIBUTE,
                "claim": LinkagePurpose.CLAIM,
            }[purpose],
        )

        if not all(comparisons):
            raise AssertionEvaluationMappingError(
                "Linkage token identity is invalid."
            )

    def _validate_assertion_response(
        self,
        result,
    ) -> EvaluateAssertionResponse:
        if not isinstance(
            result,
            CallToolResult,
        ):
            raise AssertionEvaluationResponseError(
                "Evaluator returned an invalid response."
            )

        if result.isError:
            try:
                error = (
                    OmneumErrorResponse.model_validate(
                        result.structuredContent,
                        strict=True,
                    )
                )
            except ValidationError:
                raise AssertionEvaluationResponseError(
                    "Evaluator returned an invalid "
                    "structured error."
                ) from None

            raise AssertionEvaluationRejectedError(
                error.omneum_code
            )

        try:
            response = (
                EvaluateAssertionResponse.model_validate(
                    result.structuredContent,
                    strict=True,
                )
            )
        except ValidationError:
            raise AssertionEvaluationResponseError(
                "Evaluator returned an invalid "
                "success response."
            ) from None

        pinned = (
            response.protocol_version
            == PROTOCOL_VERSION,
            response.deployment_id
            == self._config.deployment_id,
            response.voprf_key_version
            == self._config.voprf_key_version,
            response.voprf_mode
            == self._config.voprf_mode,
            response.voprf_ciphersuite
            == self._config.voprf_ciphersuite,
            response.linkage_encoding_version
            == self._config.linkage_encoding_version,
        )

        if not all(pinned):
            raise AssertionEvaluationResponseError(
                "Assertion-evaluation metadata "
                "does not match the pin."
            )

        metadata = response.metadata

        if (
            metadata.algorithm_version
            != ALGORITHM_VERSION
            or not metadata.converged
            or metadata.convergence_tolerance
            != CONVERGENCE_TOLERANCE
            or not 1 <= metadata.iterations <= 1000
        ):
            raise AssertionEvaluationResponseError(
                "Assertion-evaluation convergence "
                "metadata is invalid."
            )

        return response

    async def _evaluate(
        self,
        blind: LinkageBlindResult,
    ) -> LinkageToken:
        request = EvaluateVOPRFRequest(
            protocol_version=PROTOCOL_VERSION,
            deployment_id=(
                self._config.deployment_id
            ),
            voprf_key_version=(
                self._config.voprf_key_version
            ),
            voprf_mode=self._config.voprf_mode,
            voprf_ciphersuite=(
                self._config.voprf_ciphersuite
            ),
            linkage_encoding_version=(
                self._config.linkage_encoding_version
            ),
            blinded_element=encode_unpadded(
                blind.blinded_element,
                expected_length=ELEMENT_LENGTH,
            ),
        )

        try:
            result = (
                await self._evaluator.evaluate_voprf(
                    request
                )
            )
        except asyncio.CancelledError:
            raise
        except EvaluationTransportError:
            raise
        except Exception:
            raise EvaluationTransportError(
                uncertain=True
            ) from None

        response = self._validate_response(result)

        try:
            evaluation = VOPRFEvaluation(
                evaluated_element=decode_unpadded(
                    response.evaluated_element,
                    expected_length=ELEMENT_LENGTH,
                ),
                proof=decode_unpadded(
                    response.proof,
                    expected_length=PROOF_LENGTH,
                ),
            )
        except ValueError:
            raise EvaluationResponseError(
                "VOPRF response contains invalid "
                "protocol values."
            ) from None

        try:
            value = self._linkage.finalize(
                blind,
                evaluation,
            )
        except OPRFError:
            raise EvaluationVerificationError(
                "VOPRF proof verification or "
                "finalization failed."
            ) from None

        return LinkageToken(
            deployment_id=(
                self._config.deployment_id
            ),
            voprf_key_version=(
                self._config.voprf_key_version
            ),
            voprf_mode=self._config.voprf_mode,
            voprf_ciphersuite=(
                self._config.voprf_ciphersuite
            ),
            linkage_encoding_version=(
                self._config.linkage_encoding_version
            ),
            purpose=blind.purpose,
            value=value,
        )

    def _validate_response(
        self,
        result: CallToolResult,
    ) -> EvaluateVOPRFResponse:
        if not isinstance(
            result,
            CallToolResult,
        ):
            raise EvaluationResponseError(
                "Evaluator returned an invalid response."
            )

        if result.isError:
            try:
                error = (
                    OmneumErrorResponse.model_validate(
                        result.structuredContent,
                        strict=True,
                    )
                )
            except ValidationError:
                raise EvaluationResponseError(
                    "Evaluator returned an invalid "
                    "structured error."
                ) from None

            raise EvaluationRejectedError(
                error.omneum_code
            )

        try:
            response = (
                EvaluateVOPRFResponse.model_validate(
                    result.structuredContent,
                    strict=True,
                )
            )
        except ValidationError:
            raise EvaluationResponseError(
                "Evaluator returned an invalid "
                "success response."
            ) from None

        comparisons = (
            (
                response.protocol_version,
                PROTOCOL_VERSION,
            ),
            (
                response.deployment_id,
                self._config.deployment_id,
            ),
            (
                response.voprf_key_version,
                self._config.voprf_key_version,
            ),
            (
                response.voprf_mode,
                self._config.voprf_mode,
            ),
            (
                response.voprf_ciphersuite,
                self._config.voprf_ciphersuite,
            ),
            (
                response.linkage_encoding_version,
                self._config.linkage_encoding_version,
            ),
        )

        if any(
            actual != expected
            for actual, expected in comparisons
        ):
            raise EvaluationResponseError(
                "Evaluator response metadata "
                "does not match the pin."
            )

        return response


class _MCPOmneumEvaluator:
    def __init__(
        self,
        session: ClientSession,
    ) -> None:
        self._session = session
        self._closed = False

    async def evaluate_voprf(
        self,
        request: EvaluateVOPRFRequest,
    ) -> CallToolResult:
        if self._closed:
            raise EvaluationTransportError(
                uncertain=False
            )

        try:
            return await self._session.call_tool(
                "evaluate_voprf",
                request.model_dump(mode="json"),
            )
        except Exception:
            raise EvaluationTransportError(
                uncertain=True
            ) from None

    async def evaluate_assertion(
        self,
        request: EvaluateAssertionRequest,
    ) -> CallToolResult:
        if self._closed:
            raise AssertionEvaluationTransportError(
                uncertain=False
            )

        try:
            return await self._session.call_tool(
                "evaluate_assertion",
                request.model_dump(mode="json"),
            )
        except Exception:
            raise AssertionEvaluationTransportError(
                uncertain=True
            ) from None

    def close(self) -> None:
        self._closed = True


@asynccontextmanager
async def open_stdio_client(
    config: OmneumClientConfig,
    server: StdioServerParameters,
) -> AsyncIterator[OmneumClient]:
    """Open and own one local MCP stdio subprocess and client session."""

    if (
        isinstance(server, StdioServerParameters)
        and server.env is None
    ):
        config_dir = os.environ.get("OMNEUM_CONFIG_DIR")
        if config_dir is not None:
            server = server.model_copy(
                update={
                    "env": {
                        "OMNEUM_CONFIG_DIR": config_dir,
                    }
                }
            )

    async with stdio_client(server) as (
        read,
        write,
    ):
        async with ClientSession(
            read,
            write,
        ) as session:
            try:
                await session.initialize()
                tools = await session.list_tools()
            except Exception:
                raise EvaluationTransportError(
                    uncertain=False
                ) from None

            if not any(
                tool.name == "evaluate_voprf"
                for tool in tools.tools
            ):
                raise EvaluationResponseError(
                    "The evaluate_voprf tool "
                    "is unavailable."
                )

            assertion_evaluation_available = any(
                tool.name == "evaluate_assertion"
                for tool in tools.tools
            )

            evaluator = _MCPOmneumEvaluator(
                session
            )

            try:
                yield OmneumClient(
                    config,
                    evaluator,
                    assertion_evaluation_available=(
                        assertion_evaluation_available
                    ),
                )
            finally:
                evaluator.close()


def _validate_deployment_id(
    value: object,
) -> None:
    if (
        type(value) is not str
        or not value.startswith("urn:uuid:")
    ):
        raise OmneumClientConfigurationError(
            "Deployment ID must be a "
            "canonical UUID URN."
        )

    try:
        parsed = uuid.UUID(value[9:])
    except ValueError:
        raise OmneumClientConfigurationError(
            "Deployment ID must be a "
            "canonical UUID URN."
        ) from None

    if value != f"urn:uuid:{parsed}":
        raise OmneumClientConfigurationError(
            "Deployment ID must be a "
            "canonical UUID URN."
        )


def _snapshot_observations(values):
    result = []

    for value in values:
        source = Source(
            kind=value.source.kind,
            identifier=canonicalize_source(
                value.source.kind,
                value.source.identifier,
            ),
            owner_id=value.source.owner_id,
        )

        claim = Claim(
            value.claim.entity_namespace,
            canonicalize_entity(
                value.claim.entity_namespace,
                value.claim.entity,
            ),
            canonicalize_attribute(
                value.claim.attribute
            ),
            value.claim.value,
        )

        upstream_sources = None

        if value.upstream_sources is not None:
            upstream_sources = tuple(
                SourceReference(
                    item.kind,
                    canonicalize_source(
                        item.kind,
                        item.identifier,
                    ),
                )
                for item in value.upstream_sources
            )

        cited_sources = None

        if value.cited_sources is not None:
            cited_sources = tuple(
                SourceReference(
                    item.kind,
                    canonicalize_source(
                        item.kind,
                        item.identifier,
                    ),
                )
                for item in value.cited_sources
            )

        retrievals = None

        if value.retrievals is not None:
            retrievals = tuple(
                Retrieval(
                    retrieval_id=item.retrieval_id,
                    kind=item.kind,
                    resource_id=item.resource_id,
                    retrieved_at=item.retrieved_at,
                    fields=item.fields,
                )
                for item in value.retrievals
            )

        result.append(
            Observation(
                assertion_id=value.assertion_id,
                source=source,
                claim=claim,
                observed_at=value.observed_at,
                source_modified_at=(
                    value.source_modified_at
                ),
                upstream_sources=upstream_sources,
                cited_sources=cited_sources,
                parent_assertion_ids=(
                    value.parent_assertion_ids
                ),
                retrievals=retrievals,
            )
        )

    return tuple(result)


def _compare_assertion_evaluation(
    response,
    expected,
) -> None:
    if (
        response.summary.source_count
        != expected.summary.source_count
        or response.summary.claim_count
        != expected.summary.claim_count
        or response.summary.assertion_count
        != expected.summary.assertion_count
        or response.metadata.algorithm_version
        != expected.metadata.algorithm_version
        or response.metadata.iterations
        != expected.metadata.iterations
        or response.metadata.converged
        != expected.metadata.converged
        or response.metadata.convergence_tolerance
        != expected.metadata.convergence_tolerance
        or response.metadata.convergence_delta
        != expected.metadata.convergence_delta
    ):
        raise AssertionEvaluationResponseError(
            "Assertion-evaluation response "
            "is inconsistent."
        )

    actual_sources = tuple(
        (
            item.source_id,
            item.reliability,
        )
        for item in response.source_reliability
    )

    expected_sources = tuple(
        (
            item.source_id,
            item.reliability,
        )
        for item in expected.source_reliability
    )

    if actual_sources != expected_sources:
        raise AssertionEvaluationResponseError(
            "Source-reliability results "
            "are inconsistent."
        )

    actual_claims = tuple(
        (
            item.attribute_id,
            item.claim_id,
            item.support,
            item.agreement_weight,
            item.is_attribute_max_support,
            item.supporting_source_count,
            item.estimated_independent_support_count,
            item.dependency_confidence,
            tuple(
                (
                    source.source_id,
                    source.independence,
                    source.contribution,
                )
                for source
                in item.supporting_sources
            ),
            tuple(
                (
                    claim.claim_id,
                    claim.support,
                )
                for claim
                in item.conflicting_claims
            ),
        )
        for item in response.claim_support
    )

    expected_claims = tuple(
        (
            item.attribute_id,
            item.claim_id,
            item.support,
            item.agreement_weight,
            item.is_attribute_max_support,
            item.supporting_source_count,
            item.estimated_independent_support_count,
            item.dependency_confidence,
            tuple(
                (
                    source.source_id,
                    source.independence,
                    source.contribution,
                )
                for source
                in item.supporting_sources
            ),
            tuple(
                (
                    claim.claim_id,
                    claim.support,
                )
                for claim
                in item.conflicting_claims
            ),
        )
        for item in expected.claim_support
    )

    if actual_claims != expected_claims:
        raise AssertionEvaluationResponseError(
            "Claim-support results are inconsistent."
        )


def _validate_mapping(
    response,
    sources,
    attributes,
    claims,
) -> None:
    for item in response.source_reliability:
        if item.source_id not in sources:
            raise AssertionEvaluationMappingError(
                "Assertion-evaluation token "
                "mapping is invalid."
            )

    for item in response.claim_support:
        if (
            item.attribute_id not in attributes
            or item.claim_id not in claims
        ):
            raise AssertionEvaluationMappingError(
                "Assertion-evaluation token "
                "mapping is invalid."
            )

        if any(
            source.source_id not in sources
            for source in item.supporting_sources
        ):
            raise AssertionEvaluationMappingError(
                "Assertion-evaluation token "
                "mapping is invalid."
            )

        if any(
            claim.claim_id not in claims
            for claim in item.conflicting_claims
        ):
            raise AssertionEvaluationMappingError(
                "Assertion-evaluation token "
                "mapping is invalid."
            )


def _map_assertion_evaluation(
    response,
    source_objects,
    claim_objects,
    pairs,
    threshold,
):
    source_results = tuple(
        SourceEvaluation(
            source_objects[item.source_id],
            item.reliability,
        )
        for item in response.source_reliability
    )

    claim_results = []

    for item in response.claim_support:
        clusters = None

        if threshold is not None:
            source_keys = {
                token: (
                    source.kind,
                    canonicalize_source(
                        source.kind,
                        source.identifier,
                    ),
                )
                for token, source
                in source_objects.items()
            }

            supporting = {
                source_keys[source.source_id]
                for source
                in item.supporting_sources
            }

            ordered_sources = tuple(
                sorted(
                    supporting,
                    key=lambda source: (
                        serialize_source(*source)
                    ),
                )
            )

            adjacency = {
                source: set()
                for source in supporting
            }

            for pair in pairs:
                a = (
                    pair.source_a.kind,
                    pair.source_a.identifier,
                )

                b = (
                    pair.source_b.kind,
                    pair.source_b.identifier,
                )

                if (
                    a in supporting
                    and b in supporting
                    and pair.dependency >= threshold
                ):
                    adjacency[a].add(b)
                    adjacency[b].add(a)

            remaining = set(supporting)
            values = []

            for start in ordered_sources:
                if start not in remaining:
                    continue

                stack = [start]
                component = set()
                remaining.remove(start)

                while stack:
                    current = stack.pop()
                    component.add(current)

                    for other in reversed(
                        ordered_sources
                    ):
                        if (
                            other
                            not in adjacency[current]
                        ):
                            continue

                        if other in remaining:
                            remaining.remove(other)
                            stack.append(other)

                values.append(
                    DependencyCluster(
                        threshold,
                        tuple(
                            SourceReference(*source)
                            for source
                            in ordered_sources
                            if source in component
                        ),
                    )
                )

            clusters = tuple(values)

        claim_results.append(
            ClaimSupportResult(
                claim=claim_objects[
                    item.claim_id
                ],
                support=item.support,
                agreement_weight=(
                    item.agreement_weight
                ),
                is_attribute_max_support=(
                    item.is_attribute_max_support
                ),
                supporting_source_count=(
                    item.supporting_source_count
                ),
                estimated_independent_support_count=(
                    item.estimated_independent_support_count
                ),
                dependency_confidence=(
                    item.dependency_confidence
                ),
                supporting_sources=tuple(
                    SupportingSourceResult(
                        source_objects[
                            source.source_id
                        ],
                        source.independence,
                        source.contribution,
                    )
                    for source
                    in item.supporting_sources
                ),
                conflicting_claims=tuple(
                    ConflictingClaimResult(
                        claim_objects[
                            claim.claim_id
                        ],
                        claim.support,
                    )
                    for claim
                    in item.conflicting_claims
                ),
                dependency_clusters=clusters,
            )
        )

    metadata = response.metadata

    return AssertionEvaluation(
        source_results,
        tuple(claim_results),
        pairs,
        ConvergenceMetadata(
            metadata.algorithm_version,
            metadata.iterations,
            metadata.converged,
            metadata.convergence_tolerance,
            metadata.convergence_delta,
        ),
        threshold,
    )
