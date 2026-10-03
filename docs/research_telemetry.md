# Opt-in research telemetry, v1

Research recording is opt-in: wrap an evaluation with
`omneum.research_telemetry.record_evaluation` to record aggregate research events.
It is separate from operational metrics and logs, preserves `MetricsRecorder`
behavior, and requires no changes to SDK signatures, MCP payloads or VOPRF flows.

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
    lambda: client.evaluate_context(observations, estimator=estimator),
    estimator=estimator,
    context=context,
    recorder=JsonlResearchRecorder("/private/research/events.jsonl"),
)
```

Use the actual implementation revision, not the upstream specification SHA.
`checkout_provenance(checkout)` can obtain a local Git revision and dirty state.
Installed code without verified build provenance uses
`ImplementationProvenance()` (unknown). Supplied provenance is explicitly
labeled as such, not authenticated. Never claim clean provenance for dirty
local code. Remote-server revision is separately optional/unknown: the SDK's
local verification does not establish the server's build identity.

Verified-checkout provenance requires `checkout_provenance`, which binds a
private, nonserialized receipt to the checked revision and state. Parsing a
historical record preserves its labels but does not authenticate them or grant
that receipt. Parsed records cannot be emitted as newly verified events;
recheck the checkout for a new evaluation.

Each invocation emits at most one completion event on success, exception or
cancellation. Original results and exceptions, including evaluation cancellation,
are preserved. Recorder failures, including `BaseException` subclasses, produce
only a fixed operational warning, never exception contents. Failures in recording
or warning delivery cannot change evaluation behavior. Latency measures the wrapped
operation and excludes recording. Failure statistics not exposed by production
remain null rather than guessed. This wrapper does not instrument arbitrary
unwrapped or direct server requests.

## Schema and privacy

`omneum/schemas/research-event-v1.schema.json` is the explicit versioned wire
schema. The strict Pydantic model validates emitted and consumed records;
unknown fields and schema versions fail closed. Tests keep schema and model
in sync.

Events contain only:

- random event/run IDs, UTC completion time and optional UUID evidence/reproducer IDs;
- normative algorithm identity/version/revision/fixture revision;
- local and optional remote implementation provenance;
- estimator identity, numeric weights/window/threshold;
- available graph dimensions and aggregate dependency, coverage and effective support;
- per-signal raw observability counts and observed-value means;
- convergence metadata, outcome, allowlisted failure code and operation latency;
- optional hexadecimal trace/span correlation IDs.

Raw signal observability is distinct from fusion coverage: excluded ownership
can remain observable; disabled configured signals need not contribute coverage.
Conflict counts are directed entries, consistent with production result lists.
Empty aggregate means are null. Runtime failure codes are not operator research
classifications; the default classification is unset.

Do not serialize raw observations, prompts, source/claim identities, passages,
private documents, exception messages, arbitrary metadata, linkage tokens,
VOPRF material, secrets, API keys, URLs or content hashes. The builder only
selects aggregate fields; it never serializes the production evaluation object.
UUID references locate evidence in a separately protected registry, not through
embedded customer filenames or URLs.

Structural aggregates can still be sensitive. Recording is opt-in and local;
there is no upload, exporter, automatic publication or deployment. New JSONL
files use mode 0600 and new directories 0700 on POSIX. Existing publicly
readable files and symlink destinations are rejected on POSIX. Use a trusted
local directory; Windows deployments must enforce equivalent ACLs. One writer
per stream is supported. Writes append a complete event and fsync before
returning; I/O interruption may leave a truncated last line, which validators
report rather than silently repair.

Custom adapters can implement the recorder protocol. Optional trace/span IDs
support correlation with OpenTelemetry; recording does not require its SDK or
a collector.

## Reproduction and research

Aggregate events are not full graph reproductions. Submit a separately reviewed,
synthetic structural reproducer through the operator, or document the missing
information and how to construct one. Keep raw private evidence out of research
artifacts. Research classifications have five categories:
implementation bug, integration/mapping issue, packaging/infrastructure issue,
expected behavior, and unresolved research question.

Research questions do not trigger algorithm edits. Preserve observations,
exact revisions/configuration, equation references and non-normative candidate
directions; Cole decides whether to accept a future upstream change.
Historical event schemas and provenance remain immutable through renames.
