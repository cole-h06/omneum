"""Verity SDK."""

from .client import (
    ClaimSupportResult,
    ConflictingClaimResult,
    ConvergenceMetadata,
    AssertionEvaluation,
    EvaluationRejectedError,
    EvaluationResponseError,
    EvaluationTransportError,
    EvaluationVerificationError,
    AssertionEvaluationMappingError,
    AssertionEvaluationRejectedError,
    AssertionEvaluationResponseError,
    AssertionEvaluationTransportError,
    LinkageToken,
    SourceEvaluation,
    SupportingSourceResult,
    VerityClient,
    VerityClientConfig,
    VerityClientConfigurationError,
    VerityClientError,
    open_stdio_client,
)
from .dependency import (
    DependencyCluster,
    DependencyEvidence,
    DependencyEstimatorConfig,
    DependencySignalScores,
    PairwiseDependencyResult,
)
from .explanations import explain_claim, explain_dependency
from .information import Claim, Observation, Source, SourceReference

__version__ = "1.0.0"

__all__ = [
    "Claim",
    "ClaimSupportResult",
    "ConflictingClaimResult",
    "ConvergenceMetadata",
    "AssertionEvaluation",
    "DependencyCluster",
    "DependencyEvidence",
    "DependencyEstimatorConfig",
    "DependencySignalScores",
    "EvaluationRejectedError",
    "EvaluationResponseError",
    "EvaluationTransportError",
    "EvaluationVerificationError",
    "AssertionEvaluationMappingError",
    "AssertionEvaluationRejectedError",
    "AssertionEvaluationResponseError",
    "AssertionEvaluationTransportError",
    "LinkageToken",
    "Observation",
    "PairwiseDependencyResult",
    "Source",
    "SourceEvaluation",
    "SourceReference",
    "SupportingSourceResult",
    "VerityClient",
    "VerityClientConfig",
    "VerityClientConfigurationError",
    "VerityClientError",
    "explain_claim",
    "explain_dependency",
    "open_stdio_client",
]
