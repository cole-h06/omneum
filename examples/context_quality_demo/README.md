# Context Quality Demo

Compare retrieval-order context packing with Omneum. Both paths use the same evidence and token budget.

## Run

From the repository root:

```bash
.venv/bin/python -m examples.context_quality_demo.before_after
```

Requires the Omneum Python package. No API keys, LLM, MCP server, database, or network access.

## Workflow

Five synthetic chunks describe an enterprise support copilot. The evidence covers processing region, provider retention, customer-content redaction, and audit retention.

| Chunk | Source | Claims | Provenance |
|---|---|---|---|
| `team-faq` | Support FAQ | Region, provider retention | Derived from security policy |
| `wiki-mirror` | Internal wiki | Region, provider retention | Derived from security policy |
| `gateway-config` | Gateway configuration | Region, provider retention | No declared upstream |
| `security-policy` | Security policy | Region, provider retention, redaction | No declared upstream |
| `audit-config` | Audit configuration | Redaction, audit retention | No declared upstream |

The fixture supplies structured observations, provenance, and original chunk text. No claim extraction is performed.

Both paths use `omneum.reconstruct_context()` with the same 80-unit budget and Unicode word/punctuation counter, including chunk headers.

| Path | SDK behavior |
|---|---|
| Raw RAG | `strategy="retrieval"` packs whole chunks in retrieval order, skipping chunks that exceed the remaining budget |
| Omneum | `omneum.evaluate()` computes graph-based evidence support; `strategy="coverage_support"` selects chunks using structural support and uncovered-claim utility |

Selected chunks retain their original text. Neither path summarizes or rewrites content.

## Results

Recorded from the deterministic fixture:

| Metric | Raw RAG | Omneum |
|---|---|---|
| Selected chunks | `team-faq`, `wiki-mirror`, `gateway-config` | `security-policy`, `audit-config` |
| Chunks retained | 3/5 | 2/5 |
| Budget used | 75/80 | 51/80 |
| Distinct claims covered | 2/4 | 4/4 |
| Claim coverage | 50% | 100% |

### Raw RAG

```text
[team-faq]
The support copilot processes tickets in the EU. The hosted provider retains ticket content for zero days, per the security policy.

[wiki-mirror]
Copied from the security policy: support copilot processing stays in the EU and provider retention is zero days.

[gateway-config]
The deployed support copilot gateway reports region EU and provider content retention of zero days.
```

Three chunks consume 75 budget units. All three cover the same two claims. The redaction and audit-retention evidence is excluded.

### Omneum

```text
[security-policy]
Support copilot policy: process in the EU, require zero days of provider retention, and send only redacted customer content.

[audit-config]
The support copilot audit service accepts only redacted customer content and retains audit records for 365 days.
```

Two chunks consume 51 budget units and cover all four claims. The repeated FAQ, wiki, and gateway chunks are excluded.

## Implementation

| Component | API | Role |
|---|---|---|
| Graph evaluation | `omneum.evaluate()` | Evaluates source–claim relationships and provenance |
| Raw packing | `reconstruct_context(..., strategy="retrieval")` | Selects chunks in retrieval order |
| Graph-informed selection | `reconstruct_context(..., strategy="coverage_support")` | Selects and orders chunks under the budget |
| Context payload | `result["context"]` | Original selected text for downstream LLM input |
| Chunk mapping | `chunk_id`, `raw_text`, `claim_ids` | Links evaluated claims to original retrieved text |

The graph evaluation does not inspect `raw_text`. Reconstruction uses the supplied claim-to-chunk mappings to select original passages.

## Scope

The 80-unit budget uses the SDK's Unicode word/punctuation counter, not a model tokenizer. Claim coverage measures supplied claim mappings, not factual correctness or question relevance.

Omneum evaluates source–claim relationships and upstream provenance in-process. The example compares graph-informed context selection against retrieval-order packing. It does not separately measure dependency weighting or downstream answer accuracy.

## Files

| Path | Description |
|---|---|
| [`before_after.py`](before_after.py) | Executable comparison |
| [`../../tests/test_in_process_evaluation.py`](../../tests/test_in_process_evaluation.py) | In-process evaluation and demo tests |
