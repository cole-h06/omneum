"""Omneum SDK."""

from .mapping import ContextMapper
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

__version__ = "1.0.4"

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
