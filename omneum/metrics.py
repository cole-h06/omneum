from __future__ import annotations

import json
import math
import logging
import sys
from contextvars import ContextVar
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


# Context-local preparation measurements keep overlapping SDK calls separate.
# Process CPU and RSS still include unrelated work in this process.
_execution_telemetry = ContextVar("omneum_execution_telemetry", default=None)


def _peak_process_memory_bytes():
    if sys.platform not in ("darwin", "linux"):
        return None
    try:
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except (ImportError, OSError):
        return None
    # macOS reports bytes; Linux reports KiB. This is a lifetime high-water
    # mark sampled at evaluation completion, not memory allocated by this call.
    return int(peak * (1024 if sys.platform == "linux" else 1))


_EXECUTION_NAMES = {
    "sdk_end_to_end_latency_ms": "sdk_duration_ms",
    "graph_evaluation_latency_ms": "graph_evaluation_ms",
    "mcp_roundtrip_latency_ms": "mcp_round_trip_ms",
    "chunk_selection_latency_ms": "selection_ms",
    "context_reconstruction_latency_ms": "reconstruction_ms",
    "cpu_time_ms": "sdk_cpu_time_ms",
    "peak_memory_bytes": "sdk_peak_rss_bytes",
    "cpu_time_scope": "cpu_scope",
    "peak_memory_scope": "memory_scope",
    "evaluation_latency_ms": "evaluation_latency_ms",
    "local_inference_latency_ms": "local_inference_latency_ms",
    "input_tokens": "input_tokens",
    "selected_tokens": "selected_tokens",
    "token_budget": "token_budget",
    "reduction_ratio": "reduction_ratio",
}


class JsonExecutionFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({
            "event": "omneum.execution",
            "timestamp": record.timestamp,
            "evaluation_run_id": record.evaluation_run_id,
            "execution": {public: record.execution.get(internal)
                          for internal, public in _EXECUTION_NAMES.items()},
        }, allow_nan=False)


class HumanExecutionFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        values = record.execution
        lines = [f"{record.timestamp} {record.levelname} omneum.execution"]
        for name, label, unit, scale in (
            ("sdk_end_to_end_latency_ms", "SDK duration", "ms", 1),
            ("graph_evaluation_latency_ms", "Graph evaluation", "ms", 1),
            ("mcp_roundtrip_latency_ms", "MCP round-trip", "ms", 1),
            ("chunk_selection_latency_ms", "Selection", "ms", 1),
            ("context_reconstruction_latency_ms", "Reconstruction", "ms", 1),
            ("cpu_time_ms", "SDK CPU time", "ms", 1),
            ("peak_memory_bytes", "Peak SDK RSS", "MiB", 1024 * 1024),
        ):
            value = values.get(name)
            rendered = "unavailable" if value is None else f"{value / scale:.2f} {unit}"
            lines.append(f"  {label + ':':<22} {rendered}")
        lines.append(f"  Evidence units:        {values['input_tokens']} → {values['selected_tokens']}")
        reduction = values.get("reduction_ratio")
        lines.append("  Reduction:             " + ("unavailable" if reduction is None else f"{reduction:.2%}"))
        lines.extend(f"  {name}: {values.get(name)}" for name in ("cpu_time_scope", "peak_memory_scope"))
        return "\n".join(lines)
