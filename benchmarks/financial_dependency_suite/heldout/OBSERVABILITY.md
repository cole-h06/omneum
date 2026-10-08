# Held-out run checkpoints and diagnostics

Run from the repository root. The following command is for the next authorized
provider-backed smoke; the offline tests do not execute it:

```sh
.venv/bin/python -m benchmarks.financial_dependency_suite.heldout.run_benchmark \
  --trials 1 --run-id diagnostic-smoke-1trial
```

The exact result path is:

```text
benchmarks/financial_dependency_suite/heldout/results/diagnostic-smoke-1trial/results.jsonl
```

The run directory and empty result file are created before model warmup. The
manifest is written before benchmark execution. Each completed trial, including
selection and generation failures, is checkpointed before the next trial starts.
The checkpoint serializes the complete committed prefix to a private temporary
file in the same directory, flushes and fsyncs it, atomically replaces
`results.jsonl`, and fsyncs the directory. Readers always see a complete JSONL
file. An interrupted replacement leaves the previously committed prefix intact;
an abrupt process kill may leave an ignored `.results-*` temporary file.
The current in-flight/uncommitted trial is not guaranteed recoverable.
`summary.json` is published atomically only after all scheduled trials finish.
An existing run directory is never overwritten by a new run.

## Diagnostic fields

Every JSONL record retains its existing case, method, trial, answer score,
selection, and generation structure. Selector failures additionally have a
top-level `diagnostics` object containing:

- `provider`, `model`, `case_id`, `method`, `trial`, `failure_type`;
- `raw_output`: extracted text, or null when no text response was received;
- `stop_reason`, `finish_reasons`, and `content_block_types`, where available;
- `http_status` and `error_type` for SDK exceptions, where available.

Provider response metadata also travels through optional `response_diagnostics`
fields on selection/generation objects. Anthropic block *types* are recorded;
thinking contents and signatures are not. HTTP headers, request/response objects,
environment dictionaries, and full SDK exception bodies are not persisted.
The held-out artifact boundary redacts known credential values and common
credential forms from text. Provider-error strings on disk use a fixed message;
the exception type and HTTP status are retained separately. Extracted output is
otherwise unchanged: there is no JSON repair, continuation, retry, rescoring,
or prompt modification. Redaction happens after scoring.

## Resume

There was no resume support previously. To continue this run:

```sh
.venv/bin/python -m benchmarks.financial_dependency_suite.heldout.run_benchmark \
  --trials 1 \
  --resume benchmarks/financial_dependency_suite/heldout/results/diagnostic-smoke-1trial
```

Resume validates a versioned contract in `manifest.json`: input file hashes,
implementation source/lockfile hashes, methods, model configuration, generator
provider, trial count, estimator configuration, Python environment, and recorded
package versions. The saved records must be an ordered prefix of the exact trial
schedule, with recognized result states. An exclusive advisory lock prevents
two compliant runners from writing the same run simultaneously. Missing or
incompatible contracts and corrupt/truncated JSONL are rejected before warmup
or any provider call. Old runs without this contract cannot be resumed.

All committed records are retained, including failures and unscored answers.
Only uncommitted trials run, in the original order; completed stochastic
selections are never rerolled. A complete run resumes without provider calls and
recomputes the same summary. This is deterministic schedule continuation, not
deterministic provider output. If a response was received but not committed
before interruption, its trial must execute again and may incur another charge.
Remote service state and provider model aliases cannot be frozen by a local
checkpoint. Trial counts, prompts, budgets, and scoring rules are unchanged.

## Offline verification

```sh
HF_HUB_OFFLINE=1 .venv/bin/python -m pytest \
  benchmarks/financial_dependency_suite/heldout \
  benchmarks/financial_dependency_suite/test_provider_contracts.py \
  benchmarks/financial_dependency_suite/test_benchmark_failures.py \
  benchmarks/financial_dependency_suite/test_application_comparison.py \
  -k 'not test_vector_selection and not test_bge_selection' -q
```

New tests exercise real SDK deserialization through mocked HTTP transports for
valid, empty, thinking-only, prose, and truncated Anthropic responses and Google
429/503 errors in both selector conditions. Checkpoint tests cover interruption,
resume without retrying committed failures, incompatible contracts, invalid
records, exclusive writers, and interrupted atomic replacement. Secret tests
cover header omission, environment credentials, exception-body omission, and
credentials echoed in output text.
