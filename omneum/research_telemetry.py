import asyncio
import json
import math
import os
import stat
import subprocess
import threading
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal, Protocol
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    ValidationInfo,
    model_validator,
)

from .client import (
    AssertionEvaluation,
    AssertionEvaluationMappingError,
    AssertionEvaluationRejectedError,
    AssertionEvaluationResponseError,
    AssertionEvaluationTransportError,
    EvaluationTransportError,
)
from .compatibility import load_pin
from .dependency import (
    SIGNALS,
    DependencyEstimatorConfig,
    InformationGraphError,
)
from .engine_graph import GraphError
from .inference import InferenceError


Identifier = Annotated[
    str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
]
Revision = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
Count = Annotated[int, Field(ge=0)]
Nonnegative = Annotated[float, Field(ge=0)]
Unit = Annotated[float, Field(ge=0, le=1)]
Signal = Literal[
    "upstream",
    "citation",
    "assertion_lineage",
    "ownership",
    "temporal",
    "graph",
    "retrieval",
]
Classification = Literal[
    "implementation_bug",
    "integration_mapping",
    "packaging_infrastructure",
    "expected_behavior",
    "research_question",
]


class ClosedModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, allow_inf_nan=False
    )


class AlgorithmProvenance(ClosedModel):
    identity: Identifier
    version: Identifier
    revision: Revision
    fixture_revision: Annotated[int, Field(ge=1)]


_CHECKOUT_VERIFICATION = object()


class ImplementationProvenance(ClosedModel):
    revision: Revision | None = None
    state: Literal["clean", "dirty", "unknown"] = "unknown"
    origin: Literal["verified_checkout", "supplied", "unknown"] = "unknown"
    _verified_checkout: tuple[object, str, str] | None = PrivateAttr(
        default=None
    )

    @model_validator(mode="after")
    def consistency(self, info: ValidationInfo):
        if self.origin == "unknown" and (
            self.revision is not None or self.state != "unknown"
        ):
            raise ValueError("unknown provenance cannot assert a revision")
        if self.origin != "unknown" and self.revision is None:
            raise ValueError("implementation revision required")
        if self.origin == "verified_checkout":
            if info.context is _CHECKOUT_VERIFICATION:
                self._verified_checkout = (
                    _CHECKOUT_VERIFICATION,
                    self.revision,
                    self.state,
                )
            elif info.mode != "json":
                self.require_verification()
        return self

    def require_verification(self):
        if self.origin == "verified_checkout" and self._verified_checkout != (
            _CHECKOUT_VERIFICATION,
            self.revision,
            self.state,
        ):
            raise ValueError(
                "verified provenance requires checkout verification"
            )


class EstimatorParameters(ClosedModel):
    identity: Identifier
    weights: dict[Signal, Nonnegative]
    temporal_window_seconds: Annotated[float, Field(gt=0)]
    cluster_threshold: Unit | None

    @model_validator(mode="after")
    def all_weights(self):
        if (
            set(self.weights) != set(SIGNALS)
            or not 0 < math.fsum(self.weights.values()) < math.inf
        ):
            raise ValueError("complete finite positive-sum weights required")
        return self


class Summary(ClosedModel):
    count: Count
    minimum: Nonnegative | None
    maximum: Nonnegative | None
    mean: Nonnegative | None

    @model_validator(mode="after")
    def consistency(self):
        values = (self.minimum, self.maximum, self.mean)
        if self.count == 0:
            if any(value is not None for value in values):
                raise ValueError("empty summary must be null")
        elif (
            any(value is None for value in values)
            or self.minimum > self.maximum
        ):
            raise ValueError("invalid summary")
        elif (
            self.mean < self.minimum
            and not math.isclose(
                self.mean, self.minimum, rel_tol=1e-12, abs_tol=1e-15
            )
            or self.mean > self.maximum
            and not math.isclose(
                self.mean, self.maximum, rel_tol=1e-12, abs_tol=1e-15
            )
        ):
            raise ValueError("mean outside summary range")
        return self


class SignalSummary(ClosedModel):
    observable_pairs: Count
    total_pairs: Count
    mean_observed_value: Unit | None

    @model_validator(mode="after")
    def consistency(self):
        if self.observable_pairs > self.total_pairs or (
            self.observable_pairs == 0
        ) != (self.mean_observed_value is None):
            raise ValueError("invalid observability summary")
        return self


class GraphDimensions(ClosedModel):
    sources: Count
    claims: Count
    attributes: Count
    edges: Count
    pairs: Count
    directed_conflicts: Count


class Convergence(ClosedModel):
    converged: bool
    iterations: Count
    delta: Nonnegative
    tolerance: Annotated[float, Field(gt=0)]


class EvaluationContext(ClosedModel):
    run_id: UUID
    implementation: ImplementationProvenance
    remote_implementation: ImplementationProvenance = (
        ImplementationProvenance()
    )
    evidence_id: UUID | None = None
    reproducer_id: UUID | None = None
    trace_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")] | None = None
    span_id: Annotated[str, Field(pattern=r"^[0-9a-f]{16}$")] | None = None


class ResearchEvent(ClosedModel):
    schema_version: Literal[1] = 1
    event_type: Literal["algorithm_evaluation_completed"] = (
        "algorithm_evaluation_completed"
    )
    event_id: UUID
    timestamp: datetime
    context: EvaluationContext
    algorithm: AlgorithmProvenance
    estimator: EstimatorParameters
    outcome: Literal["succeeded", "failed", "cancelled"]
    failure_code: (
        Literal[
            "inference_failure",
            "invalid_input",
            "transport_failure",
            "mapping_failure",
            "evaluation_rejected",
            "response_failure",
            "cancelled",
            "unknown_failure",
        ]
        | None
    )
    classification: Classification | None = None
    latency_ms: Nonnegative
    graph: GraphDimensions | None
    dependency: Summary | None
    signal_coverage: Summary | None
    signals: dict[Signal, SignalSummary] | None
    effective_support: Summary | None
    convergence: Convergence | None

    @model_validator(mode="after")
    def consistency(self):
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        if (self.outcome == "cancelled") != (self.failure_code == "cancelled"):
            raise ValueError("cancellation code and outcome must agree")
        if self.outcome == "succeeded":
            if self.failure_code is not None or any(
                value is None
                for value in (
                    self.graph,
                    self.dependency,
                    self.signal_coverage,
                    self.signals,
                    self.effective_support,
                    self.convergence,
                )
            ):
                raise ValueError("successful event requires summaries")
            if (
                not self.convergence.converged
                or self.convergence.delta >= self.convergence.tolerance
            ):
                raise ValueError("successful event must converge")
            if (
                min(
                    self.graph.sources,
                    self.graph.claims,
                    self.graph.attributes,
                    self.graph.edges,
                    self.convergence.iterations,
                )
                < 1
            ):
                raise ValueError(
                    "successful graph and iterations must be nonempty"
                )
            if set(self.signals) != set(SIGNALS):
                raise ValueError("complete signal summaries required")
            if (
                self.graph.pairs
                != self.graph.sources * (self.graph.sources - 1) // 2
            ):
                raise ValueError("pair count mismatch")
            if (
                self.dependency.count != self.graph.pairs
                or self.signal_coverage.count != self.graph.pairs
            ):
                raise ValueError("summary count mismatch")
            if self.effective_support.count != self.graph.claims:
                raise ValueError("support count mismatch")
            for summary in (self.dependency, self.signal_coverage):
                if summary.maximum is not None and summary.maximum > 1:
                    raise ValueError("pair summaries must be in [0,1]")
            if any(
                signal.total_pairs != self.graph.pairs
                for signal in self.signals.values()
            ):
                raise ValueError("signal count mismatch")
        elif self.failure_code is None:
            raise ValueError("failure code required")
        return self


def checkout_provenance(checkout):
    try:
        commit = (
            subprocess.check_output(
                ["git", "-C", str(checkout), "rev-parse", "HEAD"],
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
        dirty = subprocess.check_output(
            [
                "git",
                "-C",
                str(checkout),
                "status",
                "--porcelain",
                "--untracked-files=all",
            ],
            stderr=subprocess.DEVNULL,
        )
        return ImplementationProvenance.model_validate(
            {
                "revision": commit,
                "state": "dirty" if dirty else "clean",
                "origin": "verified_checkout",
            },
            context=_CHECKOUT_VERIFICATION,
        )
    except (OSError, subprocess.CalledProcessError):
        return ImplementationProvenance()


def summarize(values):
    values = tuple(values)
    return Summary(
        count=len(values),
        minimum=min(values) if values else None,
        maximum=max(values) if values else None,
        mean=math.fsum(values) / len(values) if values else None,
    )


def build_event(
    *, context, estimator, latency_ms, evaluation=None, failure_code=None
):
    context.implementation.require_verification()
    context.remote_implementation.require_verification()
    if type(estimator) is not DependencyEstimatorConfig:
        raise TypeError("expected estimator configuration")
    pin = load_pin()
    data = {
        "event_id": uuid4(),
        "timestamp": datetime.now(timezone.utc),
        "context": context,
        "algorithm": AlgorithmProvenance(
            identity=pin["algorithm_id"],
            version=pin["algorithm_version"],
            revision=pin["git_revision"],
            fixture_revision=pin["fixture_revision"],
        ),
        "estimator": EstimatorParameters(
            identity=estimator.estimator_version,
            weights={
                name: getattr(estimator, name + "_weight") for name in SIGNALS
            },
            temporal_window_seconds=estimator.temporal_window_seconds,
            cluster_threshold=estimator.dependency_cluster_threshold,
        ),
        "outcome": (
            "cancelled"
            if failure_code == "cancelled"
            else "failed" if failure_code else "succeeded"
        ),
        "failure_code": failure_code,
        "latency_ms": latency_ms,
        "graph": None,
        "dependency": None,
        "signal_coverage": None,
        "signals": None,
        "effective_support": None,
        "convergence": None,
    }
    if evaluation is not None:
        if (
            type(evaluation) is not AssertionEvaluation
            or failure_code is not None
        ):
            raise TypeError("expected a successful assertion evaluation")
        pairs = evaluation.pairwise_dependencies
        claims = evaluation.claim_support
        data.update(
            graph=GraphDimensions(
                sources=len(evaluation.source_reliability),
                claims=len(claims),
                attributes=len(
                    {
                        (
                            item.claim.entity_namespace,
                            item.claim.entity,
                            item.claim.attribute,
                        )
                        for item in claims
                    }
                ),
                edges=sum(item.supporting_source_count for item in claims),
                pairs=len(pairs),
                directed_conflicts=sum(
                    len(item.conflicting_claims) for item in claims
                ),
            ),
            dependency=summarize(pair.dependency for pair in pairs),
            signal_coverage=summarize(
                pair.weighted_signal_coverage for pair in pairs
            ),
            effective_support=summarize(
                item.estimated_independent_support_count for item in claims
            ),
            signals={
                name: SignalSummary(
                    observable_pairs=sum(
                        getattr(pair.signals, name + "_observable")
                        for pair in pairs
                    ),
                    total_pairs=len(pairs),
                    mean_observed_value=summarize(
                        getattr(pair.signals, name)
                        for pair in pairs
                        if getattr(pair.signals, name + "_observable")
                    ).mean,
                )
                for name in SIGNALS
            },
            convergence=Convergence(
                converged=evaluation.convergence.converged,
                iterations=evaluation.convergence.iterations,
                delta=evaluation.convergence.convergence_delta,
                tolerance=evaluation.convergence.convergence_tolerance,
            ),
        )
    return ResearchEvent(**data)


class ResearchRecorder(Protocol):
    def record(self, event: ResearchEvent) -> None:
        ...


class JsonlResearchRecorder:
    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def record(self, event):
        event.context.implementation.require_verification()
        event.context.remote_implementation.require_verification()
        event = ResearchEvent.model_validate_json(event.model_dump_json())
        payload = (event.model_dump_json() + "\n").encode()
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor = os.open(
                self.path,
                os.O_WRONLY
                | os.O_APPEND
                | os.O_CREAT
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_NONBLOCK", 0),
                0o600,
            )
            try:
                status = os.fstat(descriptor)
                if not stat.S_ISREG(status.st_mode) or (
                    os.name == "posix" and status.st_mode & 0o077
                ):
                    raise ValueError(
                        "research file must be private and regular"
                    )
                if os.write(descriptor, payload) != len(payload):
                    raise OSError("incomplete research event write")
                os.fsync(descriptor)
            finally:
                os.close(descriptor)


def failure_code(error):
    for error_type, code in (
        (asyncio.CancelledError, "cancelled"),
        (InferenceError, "inference_failure"),
        (AssertionEvaluationMappingError, "mapping_failure"),
        (AssertionEvaluationTransportError, "transport_failure"),
        (EvaluationTransportError, "transport_failure"),
        (AssertionEvaluationRejectedError, "evaluation_rejected"),
        (AssertionEvaluationResponseError, "response_failure"),
        (InformationGraphError, "invalid_input"),
        (GraphError, "invalid_input"),
    ):
        if isinstance(error, error_type):
            return code
    return "unknown_failure"


async def record_evaluation(operation, *, estimator, context, recorder):
    started = time.perf_counter()

    def emit(evaluation=None, code=None):
        try:
            recorder.record(
                build_event(
                    context=context,
                    estimator=estimator,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    evaluation=evaluation,
                    failure_code=code,
                )
            )
        except BaseException:
            try:
                warnings.warn(
                    "Research telemetry could not be recorded.",
                    RuntimeWarning,
                    stacklevel=2,
                )
            except BaseException:
                pass

    try:
        result = await operation()
    except (Exception, asyncio.CancelledError) as error:
        emit(code=failure_code(error))
        raise
    emit(evaluation=result)
    return result
