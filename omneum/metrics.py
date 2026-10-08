from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class EvaluationMetrics:
    recorded_at: str
    observation_count: int
    source_count: int
    claim_count: int
    pair_count: int

    mean_dependency: float | None
    mean_weighted_signal_coverage: float | None

    mean_estimated_independent_support: float | None

    conflict_count: int

    convergence_iterations: int
    convergence_delta: float
    evaluation_latency_ms: float


class MetricsRecorder(Protocol):
    def record(self, metrics: EvaluationMetrics) -> None:
        ...


class JsonlMetricsRecorder:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def record(self, metrics: EvaluationMetrics) -> None:
        self._path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with self._path.open(
            "a",
            encoding="utf-8",
        ) as handle:
            json.dump(
                asdict(metrics),
                handle,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            handle.write("\n")


def build_evaluation_metrics(
    *,
    evaluation,
    observation_count: int,
    evaluation_latency_ms: float,
) -> EvaluationMetrics:
    pairs = evaluation.pairwise_dependencies
    claims = evaluation.claim_support

    mean_dependency = (
        math.fsum(
            pair.dependency
            for pair in pairs
        )
        / len(pairs)
        if pairs
        else None
    )

    mean_coverage = (
        math.fsum(
            pair.weighted_signal_coverage
            for pair in pairs
        )
        / len(pairs)
        if pairs
        else None
    )

    mean_independent_support = (
        math.fsum(
            claim.estimated_independent_support_count
            for claim in claims
        )
        / len(claims)
        if claims
        else None
    )

    conflict_count = sum(
        len(claim.conflicting_claims)
        for claim in claims
    )

    return EvaluationMetrics(
        recorded_at=datetime.now(timezone.utc).isoformat(),
        observation_count=observation_count,
        source_count=len(evaluation.source_reliability),
        claim_count=len(claims),
        pair_count=len(pairs),
        mean_dependency=mean_dependency,
        mean_weighted_signal_coverage=mean_coverage,
        mean_estimated_independent_support=(
            mean_independent_support
        ),
        conflict_count=conflict_count,
        convergence_iterations=evaluation.convergence.iterations,
        convergence_delta=(
            evaluation.convergence.convergence_delta
        ),
        evaluation_latency_ms=evaluation_latency_ms,
    )