"""Omneum SDK."""

from .mapping import ContextMapper
from .extraction import extract_observations
from .normalization import coalesce_observations, normalize_observations
from .client import (
    ClaimSupportResult,
    ConflictingClaimResult,
    ConvergenceMetadata,
    ContextEvaluation,
    EvaluationRejectedError,
    EvaluationResponseError,
    EvaluationTransportError,
    EvaluationVerificationError,
    ContextEvaluationMappingError,
    ContextEvaluationRejectedError,
    ContextEvaluationResponseError,
    ContextEvaluationTransportError,
    LinkageToken,
    SourceEvaluation,
    SupportingSourceResult,
    OmneumClient,
    OmneumClientConfig,
    OmneumClientConfigurationError,
    OmneumClientError,
    evaluate_context,
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
from .information import (
    Claim,
    ExactEquivalence,
    Observation,
    Retrieval,
    Source,
    SourceReference,
)
from .observations import (
    observe,
    reference,
    retrieval,
)
from .records import evaluate, evaluate_records
from .context_selection import reconstruct_context

__version__ = "1.1.5"

__all__ = [
    "ContextMapper",
    "Claim",
    "ExactEquivalence",
    "ClaimSupportResult",
    "ConflictingClaimResult",
    "ConvergenceMetadata",
    "ContextEvaluation",
    "DependencyCluster",
    "DependencyEvidence",
    "DependencyEstimatorConfig",
    "DependencySignalScores",
    "EvaluationRejectedError",
    "EvaluationResponseError",
    "EvaluationTransportError",
    "EvaluationVerificationError",
    "ContextEvaluationMappingError",
    "ContextEvaluationRejectedError",
    "ContextEvaluationResponseError",
    "ContextEvaluationTransportError",
    "LinkageToken",
    "LocalPersistenceConfig",
    "LocalPersistenceError",
    "Observation",
    "PairwiseDependencyResult",
    "Retrieval",
    "Source",
    "SourceEvaluation",
    "SourceReference",
    "SupportingSourceResult",
    "OmneumClient",
    "OmneumClientConfig",
    "OmneumClientConfigurationError",
    "OmneumClientError",
    "explain_claim",
    "explain_dependency",
    "extract_observations",
    "normalize_observations",
    "coalesce_observations",
    "evaluate",
    "evaluate_context",
    "evaluate_records",
    "reconstruct_context",
    "observe",
    "open_stdio_client",
    "reference",
    "retrieval",
]


from .local_persistence import LocalPersistenceConfig
from .contribution import (
    HTTPSContributionTransport,
    HTTPSNetworkEvaluator,
    NetworkContributionConfig,
    NetworkLinkageConfig,
    OmneumNetwork,
)
from .storage import ContextStorage, SQLiteStorage
from .client import LocalPersistenceError, NetworkContributionError

__all__ += [
    "NetworkContributionError",
    "NetworkContributionConfig",
    "NetworkLinkageConfig",
    "HTTPSContributionTransport",
    "ContextStorage",
    "SQLiteStorage",
    "HTTPSNetworkEvaluator",
    "OmneumNetwork",
]
