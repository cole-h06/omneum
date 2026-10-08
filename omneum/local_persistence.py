"""Local persistence configuration; SQLite is lazy and enabled by default."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID
from enum import Enum

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from .client import ContextEvaluation, LinkageToken
    from .dependency import DependencyEstimatorConfig
    from .information import Claim, Observation, Source
    from .storage import ContextStorage


class _DefaultLocalPersistence(Enum):
    SQLITE = "default SQLite"


# A stable workspace within each caller-owned SQLite file, independent of clients.
DEFAULT_LOCAL_WORKSPACE_ID = UUID("4b45e692-1a09-4a22-9df3-289f7b3c3277")


@dataclass(frozen=True, slots=True)
class LocalPersistenceConfig:
    """Choose a caller-controlled local storage adapter and workspace.

    Omit this configuration for default SQLite. Supply SQLiteStorage(path) for a
    custom file, or PostgresStorage(connection) and an existing workspace UUID for
    advanced PostgreSQL+AGE. SQLite opens/closes connections per transaction;
    PostgreSQL connections remain caller-owned, with caller commit control.
    """

    storage: ContextStorage | None = field(default=None, repr=False)
    workspace_id: UUID = DEFAULT_LOCAL_WORKSPACE_ID

    def __post_init__(self) -> None:
        from .storage import ContextStorage, SQLiteStorage

        if self.storage is None:
            object.__setattr__(self, "storage", SQLiteStorage())
        if not isinstance(self.storage, ContextStorage):
            raise TypeError("storage must implement ContextStorage")
        if not isinstance(self.workspace_id, UUID):
            raise TypeError("workspace_id must be a UUID")

    def _persist(
        self, *, evaluation: ContextEvaluation,
        occurrences: Sequence[tuple[Observation, LinkageToken, LinkageToken]],
        source_tokens: Mapping[Source, LinkageToken],
        claim_tokens: Mapping[Claim, LinkageToken],
        estimator: DependencyEstimatorConfig,
    ) -> None:
        self.storage.persist_context(
            workspace_id=self.workspace_id, evaluation=evaluation, occurrences=occurrences,
            source_tokens=source_tokens, claim_tokens=claim_tokens, estimator=estimator,
        )
