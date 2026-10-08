"""Local storage adapter contract. No database drivers are imported here."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from uuid import UUID

if TYPE_CHECKING:
    from ..client import ContextEvaluation, LinkageToken
    from ..dependency import DependencyEstimatorConfig
    from ..information import Claim, Observation, Source


@dataclass(frozen=True, slots=True)
class PersistedObservation:
    workspace_id: UUID
    source_id: UUID
    claim_id: UUID
    observation_id: UUID


@runtime_checkable
class ContextStorage(Protocol):
    """Atomic complete-evaluation writes to a caller-controlled local backend."""

    def transaction(self) -> AbstractContextManager:
        ...

    def persist_context(
        self, *, evaluation: ContextEvaluation, workspace_id: UUID,
        occurrences: Sequence[tuple[Observation, LinkageToken, LinkageToken]],
        source_tokens: Mapping[Source, LinkageToken],
        claim_tokens: Mapping[Claim, LinkageToken],
        estimator: DependencyEstimatorConfig,
    ) -> None:
        ...
