"""Verity SDK."""

from .client import (
    ClaimSupportResult,
    ConflictingClaimResult,
    ConvergenceMetadata,
    CredibilityResult,
    EvaluationRejectedError,
    EvaluationResponseError,
    EvaluationTransportError,
    EvaluationVerificationError,
    InferenceMappingError,
    InferenceRejectedError,
    InferenceResponseError,
    InferenceTransportError,
    LinkageToken,
    SourceCredibilityResult,
    SupportingSourceResult,
    VerityClient,
    VerityClientConfig,
    VerityClientConfigurationError,
    VerityClientError,
    open_stdio_client,
)
from .dependency import (
    DependencyCluster,
    DependencyEstimatorConfig,
    DependencySignalScores,
    PairwiseDependencyResult,
)
from .explanations import explain_claim, explain_dependency
from .graph import CredibilityGraph
from .information import Claim, Observation, Source, SourceReference

__version__ = "1.0.0"

__all__ = [
    "Claim",
    "ClaimSupportResult",
    "ConflictingClaimResult",
    "ConvergenceMetadata",
    "CredibilityGraph",
    "CredibilityResult",
    "DependencyCluster",
    "DependencyEstimatorConfig",
    "DependencySignalScores",
    "EvaluationRejectedError",
    "EvaluationResponseError",
    "EvaluationTransportError",
    "EvaluationVerificationError",
    "InferenceMappingError",
    "InferenceRejectedError",
    "InferenceResponseError",
    "InferenceTransportError",
    "LinkageToken",
    "Observation",
    "PairwiseDependencyResult",
    "Source",
    "SourceCredibilityResult",
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
