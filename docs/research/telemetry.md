# Research Telemetry

Opt-in evaluation telemetry for Omneum's reliability algorithms, benchmarking, and reproducibility. Use `omneum.research_telemetry` to record aggregate graph statistics, dependency signals, convergence metadata, implementation provenance, and execution latency.

Research telemetry runs in the Python application wrapping an evaluation. It does not modify MCP request payloads, SDK method signatures, VOPRF operations, or the existing `MetricsRecorder`.

Events are written to a local JSONL file. No remote collector or Network connection is required.

## Quick Start

```python
from uuid import uuid4

from omneum.research_telemetry import (
    EvaluationContext,
    ImplementationProvenance,
    JsonlResearchRecorder,
    record_evaluation,
)

context = EvaluationContext(
    run_id=uuid4(),
    implementation=ImplementationProvenance(
        revision="FULL_ACTUAL_OMNEUM_COMMIT_SHA",
        state="clean",
        origin="supplied",
    ),
)

result = await record_evaluation(
    lambda: client.evaluate_context(
        observations,
        estimator=estimator,
    ),
    estimator=estimator,
    context=context,
    recorder=JsonlResearchRecorder("/private/research/events.jsonl"),
)
```

`record_evaluation()` executes the supplied operation and records its aggregate telemetry. The original evaluation result is returned unchanged.

Recording is disabled unless the application explicitly calls the wrapper.

## Recording Evaluations

### Evaluation Context

`EvaluationContext` associates an evaluation with a research run and its implementation provenance.

```python
from uuid import uuid4

from omneum.research_telemetry import (
    EvaluationContext,
    ImplementationProvenance,
)

context = EvaluationContext(
    run_id=uuid4(),
    implementation=ImplementationProvenance(
        revision="FULL_ACTUAL_OMNEUM_COMMIT_SHA",
        state="clean",
        origin="supplied",
    ),
)
```

Use the revision of the Omneum implementation being evaluated, not the revision of an upstream specification.

Supplied provenance is labeled `supplied`. It is not authenticated by the recorder.

### Local Git Provenance

`checkout_provenance()` obtains the revision and working-tree state from a local Git checkout.

```python
from pathlib import Path
from omneum.research_telemetry import checkout_provenance

implementation = checkout_provenance(
    Path("/path/to/omneum")
)
```

Verified-checkout provenance includes a private, nonserialized verification receipt bound to the checked revision and working-tree state.

| Provenance | Behavior |
|---|---|
| Verified checkout | Local revision and state checked by `checkout_provenance()` |
| Supplied | Revision and state supplied by the caller; not authenticated |
| Unknown | Implementation identity cannot be verified |
| Remote server | Separately reported when available; otherwise unknown |

For installed code without verified build provenance:

```python
implementation = ImplementationProvenance()
```

Do not label a dirty checkout as clean. Local checkout verification does not establish the build identity of a remote server.

Parsing a historical event preserves its provenance labels but does not recreate the private verification receipt. Parsed events cannot be re-emitted as newly verified records. Run `checkout_provenance()` again for a new evaluation.

### JSONL Recorder

`JsonlResearchRecorder` appends versioned research events to a local JSONL stream.

```python
from omneum.research_telemetry import JsonlResearchRecorder

recorder = JsonlResearchRecorder(
    "/private/research/events.jsonl"
)
```

Each completed invocation produces at most one event.

| Property | Behavior |
|---|---|
| Format | JSON Lines |
| Output | Local filesystem |
| File permissions | `0600` for newly created files on POSIX |
| Directory permissions | `0700` for newly created directories on POSIX |
| Writers | One writer per stream |
| Durability | Append and `fsync` before returning |
| Existing public files | Rejected on POSIX |
| Symlink destinations | Rejected on POSIX |
| Interrupted writes | May leave a truncated final line |

Use a trusted local directory. Windows deployments must enforce equivalent filesystem ACLs.

Validators report truncated or malformed records rather than silently repairing them.

Custom recorders can implement the recorder protocol.

## Event Schema

The versioned wire schema is defined in:

```text
omneum/schemas/research-event-v1.schema.json
```

The corresponding strict Pydantic model validates emitted and consumed events.

Unknown fields and unsupported schema versions are rejected. Tests verify that the JSON Schema and Pydantic model remain synchronized.

### Event Fields

Research events contain aggregate evaluation data and implementation metadata.

| Group | Recorded data |
|---|---|
| Identity | Random event ID, run ID, UTC completion timestamp |
| Algorithm | Normative algorithm identity, version, revision, fixture revision |
| Implementation | Local and optional remote implementation provenance |
| Estimator | Estimator identity, weights, temporal window, thresholds |
| Graph | Available source, claim, and graph dimensions |
| Dependencies | Aggregate dependency estimates and effective independent support |
| Signals | Per-signal observability counts and observed-value means |
| Coverage | Aggregate dependency-signal coverage |
| Convergence | Available convergence metadata |
| Execution | Outcome, allowlisted failure code, operation latency |
| Evidence | Optional UUID evidence and reproducer references |
| Tracing | Optional hexadecimal trace and span IDs |

Fields unavailable from the production evaluation remain null rather than being estimated or reconstructed.

### Dependency Signals

Telemetry records observability and aggregate values for the source-dependency signals used by the estimator.

| Signal | Description |
|---|---|
| Upstream | Shared upstream lineage |
| Citation | Explicit citation relationships |
| Assertion lineage | Parent assertion or observation relationships |
| Ownership | Shared source ownership |
| Temporal | Timestamp proximity |
| Graph | Structural source redundancy |

Raw signal observability and fusion coverage are separate measurements.

A signal can be observable without contributing to the configured dependency estimate. For example, ownership information can be present even when the ownership weight is zero.

Disabled signals do not necessarily contribute to coverage.

Empty aggregate means are represented as null, not zero.

### Conflict Counts

Conflict counts represent directed entries in the production evaluation result lists.

They are not automatically deduplicated into unique unordered claim pairs.

### Execution Metrics

| Metric | Behavior |
|---|---|
| Operation latency | Measures the wrapped evaluation |
| Recording latency | Excluded from operation latency |
| Outcome | Success, exception, or cancellation |
| Failure code | Restricted to the event schema's allowlist |
| Unavailable statistics | Recorded as null |

Runtime failure codes are not research classifications.

The default research classification is unset.

## Failure Handling

`record_evaluation()` preserves the wrapped operation's result and exception behavior.

| Condition | Behavior |
|---|---|
| Evaluation succeeds | Return the original result |
| Evaluation raises | Propagate the original exception |
| Evaluation is cancelled | Preserve cancellation |
| Recorder fails | Emit a fixed operational warning |
| Warning delivery fails | Do not alter evaluation behavior |

Recorder failures, including `BaseException` subclasses, must not replace evaluation results or exceptions.

Operational warnings do not contain exception messages or arbitrary exception data.

The wrapper emits at most one completion event for each invocation.

Only evaluations explicitly wrapped with `record_evaluation()` are instrumented. Direct MCP requests, server-side evaluations, and unwrapped SDK calls are not automatically recorded.

## Privacy

The event builder selects aggregate fields from the evaluation result. It does not serialize the production `ContextEvaluation` object.

### Excluded Data

Research events must not contain:

| Category | Examples |
|---|---|
| Observation content | Raw observations, retrieved passages, prompts |
| Source identity | Source identifiers, URLs, publisher identifiers |
| Claim identity | Entities, attributes, claim values |
| Application data | Private documents, arbitrary metadata |
| Exceptions | Exception messages, stack contents |
| Cryptographic material | Linkage tokens, VOPRF keys or transcripts |
| Credentials | API keys, authentication secrets |
| Derived identifiers | Content hashes |

Optional evidence and reproducer IDs are UUID references. They identify records in a separately protected registry rather than embedding customer paths or URLs.

Structural aggregates can still reveal information about a workload. Keep telemetry disabled unless recording is explicitly authorized.

### Storage and Export

Research telemetry provides local JSONL recording only.

It does not implement:

- Automatic uploads
- Remote exporters
- Network contribution
- Automatic publication
- Research artifact deployment

Research telemetry is independent of the Omneum Network contribution pipeline.

## Reproduction

Aggregate telemetry is not a complete graph reproduction.

Reproducing an evaluation may require the original observation structure, estimator configuration, implementation revision, and relevant algorithm definitions.

Use a separately reviewed synthetic structural reproducer when an evaluation must be shared.

Keep raw private evidence outside published research artifacts.

### Research Classification

Research findings use five categories:

| Classification | Meaning |
|---|---|
| Implementation bug | Behavior differs from the implemented contract |
| Integration/mapping issue | Incorrect or incomplete application input mapping |
| Packaging/infrastructure issue | Installation, runtime, transport, or environment failure |
| Expected behavior | Output is consistent with the current algorithm |
| Unresolved research question | Behavior requires further algorithmic investigation |

Runtime error codes and research classifications are separate fields with different purposes.

Research findings do not automatically authorize algorithm changes. Changes to the mathematical specification require explicit maintainer review and approval.

Preserve the relevant observations, implementation revisions, estimator configuration, equation references, and candidate research directions when investigating unexpected behavior.

Historical event schemas and provenance records remain immutable across repository or package renames.

## OpenTelemetry

Optional hexadecimal trace and span IDs can correlate research events with application traces.

The recorder does not require the OpenTelemetry SDK, a collector, or an active tracing backend.

Correlation identifiers are metadata only; the research recorder does not export spans.

## Limitations

- Instrumentation applies only to explicitly wrapped evaluations.
- JSONL recording supports one writer per stream.
- Local checkout verification does not authenticate remote-server builds.
- Supplied provenance is not verified provenance.
- Historical event parsing does not restore verification receipts.
- Aggregate events cannot reconstruct the original Context Graph.
- Missing production metrics remain null.
- Interrupted filesystem writes can leave a truncated final JSONL record.
- POSIX permission checks do not establish equivalent Windows ACL protection.

## Reference

- `omneum.research_telemetry`
- `omneum/schemas/research-event-v1.schema.json`
- [Python SDK](../sdk.md)
- [Architecture](../architecture.md)
- [Dependency Estimation](../architecture.md#dependency-estimation)
- [API Reference](../api/)
