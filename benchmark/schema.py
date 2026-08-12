from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Scenario:
    """A benchmark scenario executed against every evaluation method."""

    identifier: str
    title: str
    description: str
    question: str
    observations: tuple[Any, ...]
    expected_answer: str


@dataclass(frozen=True, slots=True)
class MethodResult:
    """The output produced by a single evaluation method."""

    method: str
    answer: str
    latency_ms: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MetricResult:
    """A single benchmark metric."""

    name: str
    value: float
    passed: bool


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    """Complete evaluation results for one method on one scenario."""

    scenario: str
    method: str
    result: MethodResult
    metrics: tuple[MetricResult, ...]