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
    ) -> UUID:
        ...

    def persist_execution(self, *, workspace_id: UUID, evaluation_run_id: UUID,
                          execution: Mapping) -> UUID:
        ...


EXECUTION_FIELDS = (
    "sdk_end_to_end_latency_ms", "evaluation_latency_ms", "graph_evaluation_latency_ms",
    "mcp_roundtrip_latency_ms", "chunk_selection_latency_ms", "context_reconstruction_latency_ms",
    "local_inference_latency_ms", "cpu_time_ms", "peak_memory_bytes", "input_tokens",
    "selected_tokens", "token_budget", "reduction_ratio", "cpu_time_scope", "peak_memory_scope",
)


def execution_values(execution):
    import math

    if set(execution) != set(EXECUTION_FIELDS):
        raise ValueError("execution history requires the supported measurement fields only")
    for name in EXECUTION_FIELDS:
        value = execution[name]
        if name.endswith("_scope"):
            if not isinstance(value, str) or not value:
                raise ValueError("execution scope must be a nonempty string")
        elif name in ("input_tokens", "selected_tokens", "token_budget", "peak_memory_bytes"):
            if value is None and name == "peak_memory_bytes":
                continue
            if type(value) is not int or value < 0:
                raise ValueError("execution counts must be nonnegative integers")
        elif value is not None and (type(value) not in (int, float) or not math.isfinite(value)
                                    or name != "reduction_ratio" and value < 0):
            raise ValueError("execution measurements must be finite")
    if execution["selected_tokens"] > execution["token_budget"]:
        raise ValueError("selected tokens exceed the budget")
    return tuple(execution[name] for name in EXECUTION_FIELDS)
