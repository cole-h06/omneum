from __future__ import annotations

import time
import json
import logging
import sys

import asyncio
import math
import os
import uuid
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Literal, Protocol

from omneum.mcp import ClientSession, StdioServerParameters, stdio_client
from omneum.mcp.types import CallToolResult
from pydantic import ValidationError

from .metrics import (
    MetricsRecorder,
    build_evaluation_metrics,
    _execution_telemetry,
    _peak_process_memory_bytes,
)
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
    _UPSTREAM_ESTIMATOR,
    estimate_dependencies,
)
from .engine_graph import AssertionTriple, SourcePair, build_graph
from .inference import (
    ALGORITHM_VERSION,
    CONVERGENCE_TOLERANCE,
    infer,
)
from .mapping import ContextMapper
from .information import (
    Claim,
    ExactEquivalence,
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
from .serialization import serialize_attribute, serialize_claim, serialize_source
from .local_persistence import LocalPersistenceConfig, _DefaultLocalPersistence
from .contribution.config import NetworkContributionConfig
from .contribution.models import EvaluationContribution


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


class ContextEvaluationTransportError(OmneumClientError):
    def __init__(self, *, uncertain: bool) -> None:
        super().__init__("Context evaluation transport failed.")
        self.uncertain = uncertain


class ContextEvaluationRejectedError(OmneumClientError):
    def __init__(self, omneum_code: str) -> None:
        super().__init__("Context evaluation was rejected.")
        self.omneum_code = omneum_code


class ContextEvaluationResponseError(OmneumClientError):
    """The context-evaluation response was malformed or inconsistent."""


class ContextEvaluationMappingError(OmneumClientError):
    """The context-evaluation response could not be mapped locally."""


class LocalPersistenceError(OmneumClientError):
    """Evaluation succeeded, but explicitly requested local persistence failed."""

    def __init__(self, evaluation: ContextEvaluation, *, evaluation_run_id=None) -> None:
        message = ("Context preparation completed; execution history persistence failed. Evaluation was persisted."
                   if evaluation_run_id is not None else "Context evaluation succeeded; local persistence failed.")
        super().__init__(message)
        self.evaluation = evaluation
        self.evaluation_run_id = evaluation_run_id


class NetworkContributionError(OmneumClientError):
    """Evaluation succeeded; pseudonymous network contribution failed.

    A prepared contribution can be retried with its original idempotency key.
    Do not rerun evaluation to retry an uncertain ingestion request.
    """

    def __init__(
        self,
        evaluation: ContextEvaluation,
        *,
        reason: Literal["contribution_preparation_failed", "ingestion_failed_or_uncertain"],
        local_persistence_succeeded: bool,
        contribution: EvaluationContribution | None = None,
    ) -> None:
        super().__init__("Context evaluation succeeded; network contribution failed: " + reason)
        self.evaluation = evaluation
        self.reason = reason
        self.local_persistence_succeeded = local_persistence_succeeded
        self.contribution = contribution


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


def _persistence_identity(config: LocalPersistenceConfig | None) -> tuple | None:
    if config is None:
        return None
    from .storage import SQLiteStorage

    storage = config.storage
    if isinstance(storage, SQLiteStorage):
        return ("sqlite", str(storage.path.absolute()), str(config.workspace_id))
    return ("adapter", id(storage), str(config.workspace_id))


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

    @property
    def explanation(self) -> str:
        from .explanations import explain_claim
        return explain_claim(self)

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
    dependency_signal_coverage: float | None
    supporting_sources: tuple[SupportingSourceResult, ...]
    conflicting_claims: tuple[ConflictingClaimResult, ...]
    dependency_clusters: tuple[DependencyCluster, ...] | None

    @property
    def explanation(self) -> str:
        from .explanations import explain_claim
        return explain_claim(self)

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
            if self.dependency_signal_coverage is not None:
                raise ValueError(
                    "singleton dependency_signal_coverage must be None"
                )
        else:
            _result_number(
                self.dependency_signal_coverage,
                "dependency_signal_coverage",
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
                "context evaluation must be converged"
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
class ContextEvaluation:
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
    evaluation_latency_ms: float | None = field(
        default=None,
        compare=False,
        repr=False,
    )
    _preparation: dict[str, Any] | None = field(default=None, init=False, compare=False, repr=False)

    @property
    def evaluation_run_id(self) -> str | None:
        return None if self._preparation is None else self._preparation["evaluation_run_id"]

    @property
    def estimated_independent_support(self) -> float:
        """Independent support for a single claim; select claim_support otherwise."""
        if len(self.claim_support) != 1:
            raise ValueError(
                "estimated_independent_support requires exactly one claim; "
                "select a claim from claim_support for multiple claims or conflicting values"
            )
        return self.claim_support[0].estimated_independent_support_count

    @property
    def explanation(self) -> str:
        from .explanations import explain_evaluation
        return explain_evaluation(self)

    @property
    def explanations(self) -> tuple[str, ...]:
        return tuple(
            item.explanation
            for item in self.claim_support
        )

    @property
    def dependency_explanations(self) -> tuple[str, ...]:
        from .explanations import explain_dependency

        return tuple(
            explain_dependency(item)
            for item in self.pairwise_dependencies
        )

    def __post_init__(self):
        if self.evaluation_latency_ms is not None:
            _result_number(
                self.evaluation_latency_ms,
                "evaluation_latency_ms",
                minimum=0.0,
            )

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

    async def evaluate_context(
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
        context_evaluation_available: bool | None = None,
        metrics_recorder: MetricsRecorder | None = None,
        local_persistence: LocalPersistenceConfig | None | _DefaultLocalPersistence = _DefaultLocalPersistence.SQLITE,
        network_contribution: NetworkContributionConfig | None = None,
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
                    "evaluate_context",
                    None,
                )
            )
            if context_evaluation_available is None
            else context_evaluation_available
        )

        self._linkage = LinkageClient(oprf_client)
        self._metrics_recorder = metrics_recorder
        initialize_local = local_persistence is _DefaultLocalPersistence.SQLITE
        if initialize_local:
            local_persistence = LocalPersistenceConfig()
        if local_persistence is not None and type(local_persistence) is not LocalPersistenceConfig:
            raise TypeError("local_persistence must be a LocalPersistenceConfig or None")
        self._local_persistence = local_persistence
        if network_contribution is not None and type(network_contribution) is not NetworkContributionConfig:
            raise TypeError("network_contribution must be a NetworkContributionConfig or None")
        if (network_contribution is not None
                and network_contribution.linkage.public_key == config.voprf_public_key):
            raise OmneumClientConfigurationError(
                "Network linkage requires a key distinct from the local deployment key."
            )
        self._network_contribution = network_contribution
        # Runtime startup initializes the default graph; importing the package
        # and constructing a storage adapter alone still have no write effects.
        if initialize_local:
            with local_persistence.storage.transaction():
                pass

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

    async def _evaluate_mapped(
        self,
        items: Sequence[Any],
        mapper: ContextMapper,
        *,
        estimator: DependencyEstimatorConfig | None = None,
    ) -> ContextEvaluation:
        observations = mapper.map_many(items)
        return await self._evaluate_context(
            observations,
            estimator=_UPSTREAM_ESTIMATOR if estimator is None else estimator,
        )

    evaluate_mapped = _evaluate_mapped

    async def evaluate_context_with_chunks(
        self,
        observations: Sequence[Observation],
        chunks: Sequence[Mapping[str, Any]],
        *,
        estimator: DependencyEstimatorConfig,
        token_budget: int,
        strategy: str = "coverage_support",
        question: str | None = None,
        count_tokens: Callable[[str], int] | None = None,
        exact_equivalences: Sequence[ExactEquivalence] = (),
    ) -> dict[str, Any]:
        from .context_selection import reconstruct_context, token_count

        evaluation = await self._evaluate_context(
            observations, estimator=estimator, exact_equivalences=exact_equivalences,
        )
        context = reconstruct_context(
            evaluation, chunks, token_budget=token_budget, strategy=strategy,
            count_tokens=token_count if count_tokens is None else count_tokens,
            question=question,
        )
        return {"evaluation": evaluation, **context}

    async def prepare_context(
        self,
        assertion_observations: Sequence[Observation],
        chunks: Sequence[Mapping[str, Any]],
        *,
        estimator: DependencyEstimatorConfig,
        token_budget: int,
        strategy: str = "coverage_support",
        question: str | None = None,
        count_tokens: Callable[[str], int] | None = None,
        exact_equivalences: Sequence[ExactEquivalence] = (),
        token_penalty: float = 0.0,
        verbose: bool = False,
        collect_telemetry: bool = False,
        include_dependencies: bool = False,
        include_telemetry: bool = False,
        token_counter_name: str | None = None,
        user_query: str | None = None,
        anchor_count: int = 3,
        expansion_depth: int = 1,
        query_evaluation: Literal["local", "full"] = "local",
        claim_texts: Mapping[str, str] | None = None,
        semantic_model: Any = None,
        query_diagnostics: dict[str, Any] | None = None,
        token_cost_exponent: float | None = None,
        covered_claim_credit: float = 0.25,
        complementary_evidence: bool = False,
        query_conditioned_utility: bool = False,
        query_anchoring: bool = True,
        claim_relevance: Mapping[str, float] | None = None,
        relevance_threshold: float | None = None,
        chunk_relevance: Mapping[str, float] | None = None,
        relevance_score_type: Literal["similarity", "distance", "rank", "reranker_score", "normalized"] | None = None,
        candidate_discovery: Literal["all", "top_k", "expanded"] | None = None,
        candidate_count: int = 3,
        local_relevance: Literal["bm25", "minilm"] | None = None,
        evaluation: ContextEvaluation | None = None,
    ) -> dict[str, Any]:
        """Prepare original text; user_query opts into local semantic anchors.

        Query diagnostics are written to the supplied dictionary, never the
        agent result or MCP request. Missing semantics fall back to the full pool.
        Complementary packing requires each chunk's actual Source in 'source'.
        coverage_support_query uses full-graph scores and positive cosine weights;
        query_anchoring=False keeps all candidates. Injected relevance must cover
        every claim with a finite [0, 1] score, including explicit zeros.
        question uses local lexical relevance on original passage text instead.
        Query coverage allocates the converged claim support across inference's
        existing source clusters. Each cluster is covered at most once, using
        its best selected passage relevance. Distinct claims and conflicting
        values remain separate. No source independence penalty is applied again.
        Caller claim_relevance and query_anchoring=False provide explicit upstream
        relevance without changing inference or loading a model.
        relevance_threshold filters candidates by maximum claim cosine while
        retaining full-graph evaluation. Caller chunk scores require explicit
        score semantics. In complementary density packing they condition final
        utility as well as discovery, even when query_conditioned_utility=False.
        Discovery defaults to expanded and keeps boundary ties.
        Expanded discovery prioritizes its initial neighborhood; after its
        positive feasible utility is exhausted, other retrieved chunks may be
        selected at the same minimum accepted marginal utility per token.
        Exact top_k restrictions and inferred duplicate suppression are retained.
        Missing chunk scores are errors. local_relevance explicitly enables bm25 or minilm on
        chunk text; without either relevance source discovery retains the full
        structural pool. No model is loaded implicitly.
        coverage_answer is experimental and combines normalized chunk relevance,
        final source reliability and claim support with best-passage coverage.
        query_conditioned_utility requires available normalized chunk relevance.
        Complementary density uses inferred cluster support mass, not an extra
        source independence multiplier. coverage_support_nonlinear without
        complementary_evidence retains its experimental diminishing repetitions
        and exact-text duplicate suppression, with default token exponent .8.
        Optional claim weights remain separate from chunk weights. Normalized
        chunk scores preserve explicit zeros; other score types use pool ranks.
        evaluation reuses an unchanged SDK result with identical inputs and storage.
        Persistent evaluations support one preparation; query reuse requires full evaluation.
        """
        from .agent_result import _serialize_context_result
        from .context_selection import reconstruct_context, reconstruct, token_count
        from .explanations import explain_evaluation

        if type(verbose) is not bool or type(collect_telemetry) is not bool:
            raise TypeError("verbose and collect_telemetry must be bools")
        if type(include_dependencies) is not bool or type(include_telemetry) is not bool:
            raise TypeError("include_dependencies and include_telemetry must be bools")
        if token_counter_name is None:
            token_counter_name = "unicode_word_punctuation_proxy" if count_tokens is None or count_tokens is token_count else "custom"
        if type(token_counter_name) is not str or not token_counter_name:
            raise ValueError("token_counter_name must be a nonempty description")
        measurements = {} if collect_telemetry or include_telemetry or self._local_persistence is not None else None
        started = time.perf_counter() if measurements is not None else None
        token = _execution_telemetry.set(measurements)
        try:
            receipt = None
            if evaluation is not None:
                if type(evaluation) is not ContextEvaluation or evaluation._preparation is None:
                    raise ValueError("evaluation must be an unchanged SDK evaluation")
                receipt = evaluation._preparation
                if (receipt["observations"] != _snapshot_observations(tuple(assertion_observations))
                        or receipt["estimator"] != estimator
                        or receipt["exact_equivalences"] != tuple(exact_equivalences)
                        or receipt["config"] != self._config):
                    raise ValueError("evaluation inputs or deployment do not match")
                if receipt["persistence"] != _persistence_identity(self._local_persistence):
                    raise ValueError("evaluation persistence destination does not match")
                if receipt["prepared"]:
                    raise ValueError("evaluation already has a completed context preparation")
                if self._network_contribution is not None:
                    raise ValueError("evaluation reuse is unavailable with network contribution")
            nonlinear = strategy == "coverage_support_nonlinear"
            if question is not None:
                if type(question) is not str:
                    raise TypeError("question must be a string")
                if not question.strip():
                    question = None
                else:
                    if user_query is not None or claim_relevance is not None or query_conditioned_utility:
                        raise ValueError("question cannot be combined with other query relevance inputs")
                    if strategy == "coverage_support":
                        strategy = "coverage_support_query"
                    elif strategy != "coverage_support_query":
                        raise ValueError("question requires default or question-aware coverage selection")
            if token_cost_exponent is None:
                token_cost_exponent = 0.8 if nonlinear else 0.0
            plan = None
            if type(query_conditioned_utility) is not bool:
                raise TypeError("query_conditioned_utility must be a bool")
            if query_conditioned_utility and (strategy != "coverage_support_density"
                    or not complementary_evidence or token_penalty):
                raise ValueError("query-conditioned utility requires complementary density and zero token penalty")
            if local_relevance not in (None, "bm25", "minilm"):
                raise ValueError("local relevance must be bm25 or minilm")
            if type(candidate_count) is not int or candidate_count < 1:
                raise ValueError("candidate count must be a positive integer")
            retriever_candidates = (chunk_relevance is not None or relevance_score_type is not None
                                    or candidate_discovery is not None or local_relevance is not None
                                    or strategy == "coverage_answer" or query_conditioned_utility or nonlinear)
            if retriever_candidates:
                if nonlinear:
                    if claim_relevance is not None:
                        from .context_selection import validate_claim_relevance, claim_id
                        validate_claim_relevance(claim_relevance, {claim_id(o.claim) for o in assertion_observations})
                    if relevance_threshold is not None and (type(relevance_threshold) not in (int, float)
                            or not 0 <= relevance_threshold <= 1):
                        raise ValueError("nonlinear relevance threshold must be in [0, 1]")
                elif strategy == "coverage_answer":
                    if complementary_evidence or token_cost_exponent or token_penalty:
                        raise ValueError("answer coverage uses fixed density without another dependency penalty")
                elif strategy == "coverage_support_query":
                    if complementary_evidence or token_cost_exponent or token_penalty:
                        raise ValueError("query coverage uses fixed density without another dependency penalty")
                elif strategy != "coverage_support_density" or not complementary_evidence or (token_cost_exponent != 1 and not query_conditioned_utility) or token_penalty:
                    raise ValueError("retriever discovery requires complementary density packing with gamma=1 and lambda=0")
                if not nonlinear and (claim_relevance is not None or relevance_threshold is not None):
                    raise ValueError("chunk discovery cannot be combined with claim relevance or a relevance threshold")
                if chunk_relevance is None and relevance_score_type is not None:
                    raise ValueError("relevance score type requires caller chunk scores")
            query_weighted = strategy == "coverage_support_query"
            use_chunk_query_weights = query_conditioned_utility or nonlinear or strategy == 'coverage_answer'
            if claim_relevance is not None and not query_weighted and not complementary_evidence and not nonlinear:
                raise ValueError("claim relevance requires coverage_support_query or complementary evidence")
            if not nonlinear and relevance_threshold is not None and user_query is None and claim_relevance is None:
                raise ValueError("relevance threshold requires a query or complete relevance mapping")
            if query_weighted and (token_penalty or token_cost_exponent or complementary_evidence):
                raise ValueError("query coverage uses gamma=1, lambda=0 and distinct-claim coverage")
            if query_weighted and user_query is None and claim_relevance is None and question is None and not (retriever_candidates and (chunk_relevance is not None or local_relevance is not None)):
                raise ValueError("query coverage requires a user query or complete relevance mapping")
            evaluation_options = {"estimator": estimator, "exact_equivalences": exact_equivalences}
            if query_diagnostics is not None and type(query_diagnostics) is not dict:
                raise TypeError("query diagnostics must be a dictionary")
            if user_query is not None or claim_relevance is not None or retriever_candidates:
                from .query_context import plan_context, source_key

                if query_evaluation not in ("local", "full"):
                    raise ValueError("query evaluation must be local or full")
                if query_weighted or relevance_threshold is not None or retriever_candidates:
                    # Relevance conditions selection only. Keep normalization,
                    # dependency adjustment and propagation on the complete graph.
                    query_evaluation = "full"
                if query_evaluation == "local" and self._network_contribution is not None:
                    raise ValueError("network contributions require full query evaluation")
                query = "" if user_query is None else user_query
                if type(query) is not str:
                    raise TypeError("user query must be a string")
                if retriever_candidates:
                    query = ""
                plan_relevance = claim_relevance
                if query_weighted and retriever_candidates and (chunk_relevance is not None or local_relevance is not None) and plan_relevance is None:
                    from .context_selection import claim_id
                    plan_relevance = {claim_id(o.claim): 1.0 for o in assertion_observations}
                plan = plan_context(assertion_observations, chunks, estimator=estimator,
                    user_query=query,
                    anchor_count=anchor_count, expansion_depth=expansion_depth,
                    claim_texts=claim_texts if not retriever_candidates else None,
                    semantic_model=semantic_model,
                    query_anchoring=False if retriever_candidates else query_anchoring, query_weighted=query_weighted,
                    claim_relevance=None if nonlinear else plan_relevance,
                    relevance_threshold=None if nonlinear else relevance_threshold)
                if retriever_candidates:
                    from .query_context import discover_chunks, local_chunk_relevance

                    scores = chunk_relevance
                    score_type = relevance_score_type
                    diagnostics = plan["diagnostics"]
                    diagnostics["relevance_source"] = "caller" if scores is not None else "structural"
                    if scores is not None:
                        diagnostics["fallback_reason"] = None
                    elif local_relevance is not None:
                        local_started = time.perf_counter()
                        if not user_query or not user_query.strip():
                            diagnostics["fallback_reason"] = "empty_query"
                        elif not chunks:
                            diagnostics["fallback_reason"] = "empty_chunks"
                        else:
                            try:
                                scores = local_chunk_relevance(user_query, chunks, local_relevance, semantic_model)
                            except (ImportError, OSError, RuntimeError):
                                diagnostics["fallback_reason"] = "local_relevance_unavailable"
                            else:
                                if nonlinear:
                                    # BM25 has an unbounded nonnegative scale; cosine is bounded.
                                    if local_relevance == "bm25":
                                        maximum = max(scores.values(), default=0.0)
                                        scores = {k: v / maximum if maximum else 0.0 for k, v in scores.items()}
                                    score_type = "normalized"
                                else:
                                    score_type = "similarity"
                                diagnostics["relevance_source"] = local_relevance
                                diagnostics["fallback_reason"] = None
                        diagnostics["semantic_latency_ms"] = (time.perf_counter() - local_started) * 1000
                    else:
                        diagnostics["fallback_reason"] = "no_relevance"
                    discovery_started = time.perf_counter()
                    discovery = discover_chunks(plan["full_observations"], plan["mapping"], scores,
                        score_type, ("all" if nonlinear else "expanded") if candidate_discovery is None else candidate_discovery,
                        candidate_count, expansion_depth)
                    diagnostics.update(discovery)
                    if scores is not None and (query_weighted or (strategy == 'coverage_support_density' and complementary_evidence)):
                        # Caller query scores condition packing, not just entry
                        # points. Inferred support mass is not discounted again.
                        use_chunk_query_weights = True
                        diagnostics['final_utility'] = 'inferred_support_mass_times_query_relevance'
                    if (strategy == "coverage_answer" or query_conditioned_utility or nonlinear) and scores is None:
                        raise ValueError("query-conditioned coverage requires caller scores or available explicit local relevance")
                    diagnostics["candidate_discovery_latency_ms"] = (time.perf_counter() - discovery_started) * 1000
                    eligible = set(discovery["eligible_chunk_ids"])
                    if nonlinear and relevance_threshold is not None:
                        filtered = {k for k in eligible if discovery["normalized_relevance_scores"][k] < relevance_threshold}
                        eligible -= filtered
                        diagnostics["excluded_chunks"].extend(
                            {"chunk_id": k, "relevance": discovery["normalized_relevance_scores"][k],
                             "reason": "below_normalized_threshold"}
                            for k in plan["mapping"]["retrieval_order"] if k in filtered)
                        diagnostics["eligible_chunk_ids"] = [k for k in plan["mapping"]["retrieval_order"] if k in eligible]
                    plan["full_chunks"] = list(chunks)
                    plan["chunks"] = [chunk for chunk in chunks if chunk["chunk_id"] in eligible]
                    # Candidate restriction never changes graph initialization,
                    # dependency estimation or the full-graph inference inputs.
                    plan["observations"] = plan["full_observations"]
                chunks = plan["chunks"]
                assertion_observations = plan["observations"] if query_evaluation == "local" else plan["full_observations"]
                evaluation_options["_dependency_pairs"] = plan["pairs"]
                all_sources = {source_key(o.source) for o in plan["full_observations"]}
                for equivalence in exact_equivalences:
                    if type(equivalence) is not ExactEquivalence:
                        raise TypeError("exact_equivalences must contain ExactEquivalence values")
                    endpoints = tuple(source_key(s) for s in (equivalence.source_a, equivalence.source_b))
                    if any(s not in all_sources for s in endpoints):
                        raise ValueError("exact equivalence contains an unknown source")
                    if endpoints[0] == endpoints[1]:
                        raise ValueError("exact equivalence endpoints must be distinct")
                sources = {source_key(o.source) for o in assertion_observations}
                evaluation_options["exact_equivalences"] = tuple(e for e in exact_equivalences
                    if source_key(e.source_a) in sources and source_key(e.source_b) in sources)
                plan["diagnostics"]["evaluation_scope"] = query_evaluation
                if query_diagnostics is not None:
                    query_diagnostics.update(plan["diagnostics"])
            if evaluation is None:
                evaluation = await self._evaluate_context(assertion_observations, **evaluation_options)
            else:
                if plan is not None and query_evaluation != "full":
                    raise ValueError("evaluation reuse requires full query evaluation")
                if measurements is not None:
                    measurements.update(receipt["measurements"])
            deferred_chunk_ids = ()
            if (plan is not None and retriever_candidates
                    and plan["diagnostics"].get("candidate_discovery") == "expanded"
                    and strategy in ("coverage_support_density", "coverage_support_query")):
                # Keep the expanded neighborhood first. Only after its positive
                # feasible marginal utility is exhausted may packing search the
                # rest of the original pool, with the same full-graph inference.
                initial_ids = {chunk["chunk_id"] for chunk in chunks}
                deferred_chunk_ids = tuple(k for k in plan["mapping"]["retrieval_order"]
                                           if k not in initial_ids)
                if deferred_chunk_ids:
                    chunks = plan["full_chunks"]
            selection_trace = [] if query_diagnostics is not None else None
            selected = reconstruct_context(
                evaluation, chunks, token_budget=token_budget, strategy=strategy,
                count_tokens=token_count if count_tokens is None else count_tokens,
                token_penalty=token_penalty,
                token_cost_exponent=token_cost_exponent, complementary_evidence=complementary_evidence,
                covered_claim_credit=covered_claim_credit,
                claim_relevance=(plan["diagnostics"]["relevance_scores"]
                                 if query_weighted and plan is not None
                                 else claim_relevance if nonlinear else None),
                question=question,
                chunk_relevance={chunk["chunk_id"]: plan["diagnostics"]["normalized_relevance_scores"][chunk["chunk_id"]]
                                 for chunk in chunks} if use_chunk_query_weights else None,
                _allow_unmapped_claims=plan is not None,
                _selection_trace=selection_trace,
                _deferred_chunk_ids=deferred_chunk_ids,
            )
            considered = selected.pop("_recovery_considered_chunk_ids", [])
            recovery_floor = selected.pop("_recovery_utility_floor", None)
            if deferred_chunk_ids:
                diagnostics = plan["diagnostics"]
                diagnostics["initial_eligible_chunk_ids"] = list(diagnostics["eligible_chunk_ids"])
                diagnostics["recovery_considered_chunk_ids"] = considered
                diagnostics["recovery_utility_floor"] = recovery_floor
                diagnostics["recovered_chunk_ids"] = [k for k in selected["selected_chunk_ids"]
                                                       if k in deferred_chunk_ids]
                eligible = set(diagnostics["eligible_chunk_ids"]) | set(considered)
                diagnostics["eligible_chunk_ids"] = [k for k in plan["mapping"]["retrieval_order"] if k in eligible]
                diagnostics["excluded_chunks"] = [c for c in diagnostics["excluded_chunks"] if c["chunk_id"] not in eligible]
                if query_diagnostics is not None:
                    query_diagnostics.update(diagnostics)
            if plan is not None:
                # Input accounting covers the original retrieved pool, even
                # when inference or selection uses only a query neighborhood.
                counter = token_count if count_tokens is None else count_tokens
                count = counter(reconstruct(plan["mapping"], plan["mapping"]["retrieval_order"]))
                if type(count) is not int or count < 0:
                    raise ValueError("token counter must return a nonnegative integer")
                selected["candidate_input_tokens"] = count
                if measurements is not None:
                    measurements["query"] = plan["diagnostics"]
            # Question-only and structural selection have no discovery plan,
            # but still produce a trace. Publish it for these callers too.
            if query_diagnostics is not None:
                query_diagnostics["utility_trace"] = selection_trace
                query_diagnostics["selection_scores"] = selected["selection_scores"]
                if strategy == "coverage_answer":
                    query_diagnostics["candidate_scores"] = selected["candidate_scores"]
                query_diagnostics["selection_order"] = selected["selection_order"]
                query_diagnostics["selected_chunk_ids"] = selected["selected_chunk_ids"]
                query_diagnostics["reconstructed_context_tokens"] = selected["token_usage"]
                selected_ids = set(selected["selected_chunk_ids"])
                query_diagnostics["eligible_unselected_chunks"] = [
                    {"chunk_id": chunk["chunk_id"], "reason": "not_selected_by_packer"}
                    for chunk in chunks if chunk["chunk_id"] not in selected_ids
                ]
            result = _serialize_context_result(
                {"evaluation": evaluation, **selected}, token_counter=token_counter_name,
                include_dependencies=include_dependencies,
            )
            if measurements is not None:
                # This boundary includes evaluation persistence and preparation,
                # but excludes the final history append and diagnostic logging.
                measurements.update(
                    sdk_end_to_end_latency_ms=(time.perf_counter() - started) * 1000.0
                        + (receipt["duration_ms"] if receipt is not None else 0.0),
                    evaluation_latency_ms=evaluation.evaluation_latency_ms,
                    cpu_time_scope="sdk_process_during_evaluation",
                    peak_memory_scope="sdk_process_lifetime_peak_rss",
                    local_inference_scope="sdk_verification_infer_call",
                )
                measurements.update({name: result["selection"][name] for name in (
                    "input_tokens", "selected_tokens", "token_budget", "reduction_ratio")})
                run_id = measurements.pop("_evaluation_run_id", None)
                if self._local_persistence is not None:
                    from .storage.base import EXECUTION_FIELDS

                    execution = {name: measurements.get(name) for name in EXECUTION_FIELDS}
                    try:
                        history_id = self._local_persistence.storage.persist_execution(
                            workspace_id=self._local_persistence.workspace_id,
                            evaluation_run_id=run_id, execution=execution,
                        )
                    except Exception:
                        # The evaluation remains committed. A failed history
                        # append rolls back independently and never returns success.
                        raise LocalPersistenceError(evaluation, evaluation_run_id=run_id) from None
                    measurements.update(evaluation_run_id=str(run_id), execution_history_id=str(history_id))
                if collect_telemetry:
                    logging.getLogger("omneum.execution").info("Context prepared", extra={
                        "event": "omneum.execution",
                        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                        "evaluation_run_id": measurements.get("evaluation_run_id"),
                        "execution": measurements,
                    })
                if include_telemetry:
                    result["telemetry"] = {name: measurements.get(name) for name in (
                        "sdk_end_to_end_latency_ms", "evaluation_latency_ms", "graph_evaluation_latency_ms",
                        "mcp_roundtrip_latency_ms", "chunk_selection_latency_ms", "context_reconstruction_latency_ms",
                        "local_inference_latency_ms", "cpu_time_ms", "peak_memory_bytes",
                        "cpu_time_scope", "peak_memory_scope",
                    )}
                    json.dumps(result, allow_nan=False)
            if verbose:
                print(explain_evaluation(evaluation, concise=True), file=sys.stderr)
            if evaluation._preparation is not None and self._local_persistence is not None:
                evaluation._preparation["prepared"] = True
            return result
        finally:
            _execution_telemetry.reset(token)

    async def _evaluate_context(
        self,
        observations: Sequence[Observation],
        *,
        estimator: DependencyEstimatorConfig,
        exact_equivalences: Sequence[ExactEquivalence] = (),
        _dependency_pairs: Sequence[PairwiseDependencyResult] | None = None,
    ) -> ContextEvaluation:
        if not self._assertion_evaluation_available:
            raise ContextEvaluationResponseError(
                "The evaluate_context tool is unavailable."
            )

        values = tuple(observations)

        if any(
            (type(value) is not Observation or value.observation_type != "assertion")
            for value in values
        ):
            raise TypeError(
                "observations must contain "
                "Observation values"
            )

        values = _snapshot_observations(values)
        evaluation_started = time.perf_counter()
        measurements = _execution_telemetry.get()
        if measurements is None and self._local_persistence is not None:
            measurements = {}
        cpu_started = time.process_time() if measurements is not None else None

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

        equivalence_keys = set()
        for equivalence in exact_equivalences:
            if type(equivalence) is not ExactEquivalence:
                raise TypeError("exact_equivalences must contain ExactEquivalence values")
            endpoints = tuple(
                (source.kind, canonicalize_source(source.kind, source.identifier))
                for source in (equivalence.source_a, equivalence.source_b)
            )
            if any(endpoint not in sources_by_key for endpoint in endpoints):
                raise ValueError("exact equivalence contains an unknown source")
            if endpoints[0] == endpoints[1]:
                raise ValueError("exact equivalence endpoints must be distinct")
            equivalence_keys.add(frozenset(endpoints))

        if _dependency_pairs is None:
            pairs, _ = estimate_dependencies(tuple(sources_by_key.values()), values, estimator)
        else:
            # These pairs were estimated on the full client-side provenance
            # context. Restrict endpoints, not ancestry. Inference still runs on
            # the actual subgraph, so its normalization can change the scores.
            pairs = tuple(p for p in _dependency_pairs
                if _canonical_source_identity(p.source_a) in sources_by_key
                and _canonical_source_identity(p.source_b) in sources_by_key)

        source_tokens = {}
        source_objects = {}
        # Retain the exact already-issued tokens, without a second VOPRF call.
        persistence_tokens = {}
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
                raise ContextEvaluationMappingError(
                    "Linkage token mapping is invalid."
                )

            used_tokens.add(encoded)
            source_tokens[key] = encoded
            source_objects[encoded] = item
            if self._local_persistence is not None:
                persistence_tokens[encoded] = token

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
                    raise ContextEvaluationMappingError(
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
                    raise ContextEvaluationMappingError(
                        "Linkage token mapping "
                        "is invalid."
                    )

                used_tokens.add(encoded)
                claim_tokens[claim_key] = encoded
                if self._local_persistence is not None:
                    persistence_tokens[encoded] = token

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
                    exact_equivalence=frozenset((
                        (pair.source_a.kind, pair.source_a.identifier),
                        (pair.source_b.kind, pair.source_b.identifier),
                    )) in equivalence_keys,
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

        roundtrip_started = time.perf_counter() if measurements is not None else None
        try:
            result = (
                await self._evaluator.evaluate_context(
                    request
                )
            )
        except asyncio.CancelledError:
            raise
        except ContextEvaluationTransportError:
            raise
        except Exception:
            raise ContextEvaluationTransportError(
                uncertain=True
            ) from None

        if measurements is not None:
            measurements["mcp_roundtrip_latency_ms"] = (time.perf_counter() - roundtrip_started) * 1000.0

        response = (
            self._validate_assertion_response(
                result
            )
        )

        if measurements is not None:
            # Server time includes graph validation, executor wait, inference and
            # response-model construction; transport/JSON framing is outside it.
            measurements["graph_evaluation_latency_ms"] = response.evaluation_latency_ms

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
                    exact_equivalence=item.exact_equivalence,
                )
                for item in pair_values
            ),
        )

        inference_started = time.perf_counter() if measurements is not None else None
        expected = infer(expected_graph)
        if measurements is not None:
            measurements["local_inference_latency_ms"] = (time.perf_counter() - inference_started) * 1000.0

        _compare_assertion_evaluation(
            response,
            expected,
        )

        try:
            evaluation = _map_assertion_evaluation(
                response,
                source_objects,
                claim_objects,
                pairs,
                estimator.dependency_cluster_threshold,
            )
        except (KeyError, ValueError, TypeError):
            raise ContextEvaluationMappingError(
                "Context-evaluation response "
                "could not be mapped."
            ) from None

        evaluation_latency_ms = (
            time.perf_counter() - evaluation_started
        ) * 1000.0

        if measurements is not None:
            measurements["cpu_time_ms"] = (time.process_time() - cpu_started) * 1000.0
            measurements["peak_memory_bytes"] = _peak_process_memory_bytes()

        evaluation = replace(
            evaluation,
            evaluation_latency_ms=evaluation_latency_ms,
        )

        if self._metrics_recorder is not None:
            self._metrics_recorder.record(
                build_evaluation_metrics(
                    evaluation=evaluation,
                    observation_count=len(values),
                    evaluation_latency_ms=evaluation_latency_ms,
                )
            )

        if self._local_persistence is not None:
            try:
                run_id = self._local_persistence._persist(
                    evaluation=evaluation,
                    occurrences=tuple(
                        (observation,
                         persistence_tokens[source_tokens[row[0]]],
                         persistence_tokens[claim_tokens[row[2]]])
                        for observation, row in zip(values, canonical_rows, strict=True)
                    ),
                    source_tokens={source: persistence_tokens[token]
                                   for token, source in source_objects.items()},
                    claim_tokens={claim: persistence_tokens[token]
                                  for token, claim in claim_objects.items()},
                    estimator=estimator,
                )
                if measurements is not None:
                    measurements["_evaluation_run_id"] = run_id
            except Exception:
                # Do not expose connection strings, SQL, or private parameters
                # in a public error. The computed result remains recoverable.
                raise LocalPersistenceError(evaluation) from None

        network = self._network_contribution
        if network is not None:
            from .contribution.builder import build_contribution
            contribution = None
            try:
                contribution = await build_contribution(network, evaluation, values, estimator)
                await network.transport.submit(contribution)
            except Exception:
                raise NetworkContributionError(evaluation,
                    reason="ingestion_failed_or_uncertain" if contribution is not None else "contribution_preparation_failed",
                    local_persistence_succeeded=self._local_persistence is not None,
                    contribution=contribution) from None

        object.__setattr__(evaluation, "_preparation", {
            "observations": values,
            "estimator": estimator,
            "exact_equivalences": tuple(exact_equivalences),
            "config": self._config,
            "persistence": _persistence_identity(self._local_persistence),
            "evaluation_run_id": str(run_id) if self._local_persistence is not None else None,
            "measurements": {} if measurements is None else {
                name: value for name, value in measurements.items()
                if name in {"evaluation_latency_ms", "graph_evaluation_latency_ms", "mcp_roundtrip_latency_ms",
                            "local_inference_latency_ms", "cpu_time_ms", "peak_memory_bytes", "_evaluation_run_id"}
            },
            "duration_ms": (time.perf_counter() - evaluation_started) * 1000.0,
            "prepared": False,
        })
        return evaluation

    evaluate_context = _evaluate_context

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
            raise ContextEvaluationMappingError(
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
            raise ContextEvaluationResponseError(
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
                raise ContextEvaluationResponseError(
                    "Evaluator returned an invalid "
                    "structured error."
                ) from None

            raise ContextEvaluationRejectedError(
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
            raise ContextEvaluationResponseError(
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
            raise ContextEvaluationResponseError(
                "Context-evaluation metadata "
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
            raise ContextEvaluationResponseError(
                "Context-evaluation convergence "
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

    async def evaluate_context(
        self,
        request: EvaluateAssertionRequest,
    ) -> CallToolResult:
        if self._closed:
            raise ContextEvaluationTransportError(
                uncertain=False
            )

        try:
            return await self._session.call_tool(
                "evaluate_context",
                request.model_dump(mode="json"),
            )
        except Exception:
            raise ContextEvaluationTransportError(
                uncertain=True
            ) from None

    def close(self) -> None:
        self._closed = True


@asynccontextmanager
async def open_stdio_client(
    config: OmneumClientConfig,
    server: StdioServerParameters,
    *,
    metrics_recorder: MetricsRecorder | None = None,
    local_persistence: LocalPersistenceConfig | None | _DefaultLocalPersistence = _DefaultLocalPersistence.SQLITE,
    network_contribution: NetworkContributionConfig | None = None,
) -> AsyncIterator[OmneumClient]:
    """Open a local MCP session; default SQLite history stays in this local SDK process.

    Pass local_persistence=None to disable it, or a LocalPersistenceConfig for a
    custom adapter. Network contribution requires its own explicit configuration.
    """

    # Also accepts the official SDK's compatible StdioServerParameters model;
    # importing that separate distribution is unnecessary for this bridge.
    if getattr(server, "env", False) is None:
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

            context_evaluation_available = any(
                tool.name == "evaluate_context"
                for tool in tools.tools
            )

            evaluator = _MCPOmneumEvaluator(
                session
            )

            try:
                yield OmneumClient(
                    config,
                    evaluator,
                    context_evaluation_available=(
                        context_evaluation_available
                    ),
                    metrics_recorder=metrics_recorder,
                    local_persistence=local_persistence,
                    network_contribution=network_contribution,
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


def _evaluate_context(
    observations: Sequence[Observation],
    *,
    estimator: DependencyEstimatorConfig,
) -> ContextEvaluation:
    """Evaluate observations synchronously, entirely in memory.

    Uses the same dependency estimator, graph builder, inference engine, and
    result mapping as OmneumClient._evaluate_context. No client configuration,
    VOPRF linkage, MCP connection, daemon, or persistence is involved. Graph
    identifiers are request-scoped canonical serializations, not linkage tokens.
    Estimator weights remain an explicit caller choice.
    """
    started = time.perf_counter()
    values = tuple(observations)
    if any(type(value) is not Observation or value.observation_type != "assertion"
           for value in values):
        raise TypeError("observations must contain Observation values")
    values = _snapshot_observations(values)

    sources = {}
    for value in values:
        key = _canonical_source_identity(value.source)
        previous = sources.get(key)
        if previous is not None and previous.owner_id != value.source.owner_id:
            from .dependency import InformationGraphError

            raise InformationGraphError("canonical source has conflicting owners")
        sources.setdefault(key, value.source)

    pairs, _ = estimate_dependencies(tuple(sources.values()), values, estimator)

    # Canonical serializations preserve identity without keys or external state.
    source_ids = {
        key: serialize_source(*key).hex()
        for key in sources
    }
    source_objects = {source_ids[key]: source for key, source in sources.items()}
    claim_objects = {}
    assertions = []
    for value in values:
        claim = value.claim
        attribute = (claim.entity_namespace, claim.entity, claim.attribute)
        claim_id = serialize_claim(*attribute, claim.value).hex()
        claim_objects.setdefault(claim_id, claim)
        assertions.append(AssertionTriple(
            source_ids[_canonical_source_identity(value.source)],
            serialize_attribute(*attribute).hex(),
            claim_id,
        ))

    graph = build_graph(
        assertions,
        tuple(SourcePair(
            source_ids[_canonical_source_identity(pair.source_a)],
            source_ids[_canonical_source_identity(pair.source_b)],
            pair.dependency,
            pair.weighted_signal_coverage,
        ) for pair in pairs),
    )
    evaluation = _map_assertion_evaluation(
        infer(graph), source_objects, claim_objects, pairs,
        estimator.dependency_cluster_threshold,
    )
    return replace(
        evaluation,
        evaluation_latency_ms=(time.perf_counter() - started) * 1000.0,
    )


evaluate_context = _evaluate_context


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
                observation_id=value.observation_id,
                source=source,
                claim=claim,
                observed_at=value.observed_at,
                source_modified_at=(
                    value.source_modified_at
                ),
                upstream_sources=upstream_sources,
                cited_sources=cited_sources,
                parent_observation_ids=(
                    value.parent_observation_ids
                ),
                retrievals=retrievals,
                metadata=value.metadata,
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
        raise ContextEvaluationResponseError(
            "Context-evaluation response "
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
        raise ContextEvaluationResponseError(
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
            item.dependency_signal_coverage,
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
            item.dependency_signal_coverage,
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
        raise ContextEvaluationResponseError(
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
            raise ContextEvaluationMappingError(
                "Context-evaluation token "
                "mapping is invalid."
            )

    for item in response.claim_support:
        if (
            item.attribute_id not in attributes
            or item.claim_id not in claims
        ):
            raise ContextEvaluationMappingError(
                "Context-evaluation token "
                "mapping is invalid."
            )

        if any(
            source.source_id not in sources
            for source in item.supporting_sources
        ):
            raise ContextEvaluationMappingError(
                "Context-evaluation token "
                "mapping is invalid."
            )

        if any(
            claim.claim_id not in claims
            for claim in item.conflicting_claims
        ):
            raise ContextEvaluationMappingError(
                "Context-evaluation token "
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
                dependency_signal_coverage=(
                    item.dependency_signal_coverage
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

    return ContextEvaluation(
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
