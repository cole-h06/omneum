# What is Omneum

<p align="center">
  <img src="assets/omneum-logotype.svg" alt="Omneum" width="240">
</p>

Omneum: an open-source context evaluator for AI agents.

Agents routinely assemble context from many different sources — a RAG pipeline, web search, APIs, databases, files, memory systems, other agents — but stuffing dozens of raw chunks into a single context window can leave the model working through a mess of information that was never organized for it.

Most agents focus on retrieving more context. Omneum is focused on making sure the context reaching the model is reliable.

## Why Omneum and how it works

Modern agent pipelines use several different techniques to decide what context should reach a model:

**Semantic similarity (Vector DBs).** The piece of text that *looks* closest to the prompt wins.

**Semantic reranking.** Retrieved context is reordered based on how relevant it is to the query.

**LLM-as-a-Judge.** Another LLM reads the retrieved context and is instructed to evaluate it against a set of instructions.

While these tools are highly effective at searching and filtering for relevance, relevance is not the only important dimension of context quality.

Chunks can still hold conflicting or stale information. Multiple retrieved chunks might not be deduplicated or can appear independent even when they share the same upstream source. Without another filtering step, low-quality context can consume context-window budget that could otherwise be used for higher-quality context.

To address these problems, Omneum uses a graph-based mathematical analysis to detect conflicting claims, source redundancy, and source dependencies within retrieved context. This analysis allows Omneum to estimate a global reliability score for each source and support score for each piece of context.

These scores are entirely independent of what the source is or the semantic meaning of the context. For instance, when considering a piece of context like

“Acme reported $4.2 billion in revenue in 2025.”

It could receive a high support score if:

1. Sources with high reliability support it.
2. Those sources receive high reliability by supporting strongly supported context.

This definition seems circular, and it is. Nonetheless, it yields a well-defined notion of reliability that helps the model reason over high-quality context.

Omneum uses **BRAID**, its open-source algorithm, to compute these reliability and support scores. [Learn how BRAID works ->](https://github.com/cole-h06/braid/tree/main)

## Where Omneum fits

Omneum runs as a local MCP server as a lightweight processing step. It does not replace your existing retrieval or ranking stack; instead, it is entirely designed to run alongside them. No inference request, no extra model call:

**Retrieval / tools → Omneum evaluation → agent control flow → LLM**

Omneum returns context-quality signals; your application decides how to use them.

## Quick Start

**Note:** This tutorial assumes a Python 3.11–3.14 application. Other language SDKs are not yet available.

### 1. Install

**Supported Platforms:**

| Platform | Supported |
| --- | :---: |
| macOS (Apple Silicon / arm64) | ✅ |
| macOS (Intel / x86_64) | ✅ |
| Linux (Ubuntu 22.04+ / x86_64) | ✅ |

```bash
pip install omneum
```

### 2. Set up Omneum

```bash
omneum install
```

Run `omneum install` from your normal login account. Don't run the command with `sudo`.

The installer runs unprivileged while it downloads and verifies the evaluator release. The daemon version is pinned to the installed Python package version. For example, Omneum `1.0.3` only accepts daemon assets from `v1.0.3`; it doesn't resolve `latest` or fall back to another release.

The archive is verified against the release `SHA256SUMS` before installation. A missing checksum, mismatched digest, unexpected archive entry, link, or path traversal stops the install before anything from the archive runs.

Administrator access is requested only when installing machine-level service files. On Ubuntu, this includes the managed runtime under:

```text
/opt/omneum
```

and public client configuration at:

```text
/etc/omneum/config.toml
```

The evaluator runs as a system service because its VOPRF private key is isolated from the login account and MCP process. On macOS it runs under `launchd`; on Ubuntu it runs under systemd with a separate service identity.

`omneum-server` connects MCP clients to the installed local service. The installer finishes by sending a VOPRF request through that path and verifying the response against the configured public key. A running service alone does not count as a successful installation.

See [`docs/installation.md`](docs/installation.md) for service accounts, sockets, installed paths, custom endpoints, and failure handling.

### 3. Connect your agent

Add Omneum to your MCP client configuration:

```json
{
  "mcpServers": {
    "omneum": {
      "command": "omneum-server"
    }
  }
}
```

Restart your MCP client to expose Omneum's tools to your agent.

### 4. Verify the connection

Ask your agent to call Omneum's `ping` tool. You will receive a successful response when the MCP server and local evaluator are connected.

## Usage

Omneum evaluates a set of observations about the context your agent has assembled:

```python
from datetime import datetime, timezone

from mcp import StdioServerParameters
from omneum import (
    Claim,
    Observation,
    OmneumClientConfig,
    Source,
    open_stdio_client,
)

claim = Claim(
    entity_namespace="company",
    entity="Acme",
    attribute="revenue_2025",
    value=4_200_000_000,
)

observations = [
    Observation(
        observation_id="obs-1",
        source=Source(
            kind="web_document",
            identifier="https://example.com/acme-results",
        ),
        claim=claim,
        observed_at=datetime.now(timezone.utc),
    ),
    Observation(
        observation_id="obs-2",
        source=Source(
            kind="web_document",
            identifier="https://example.org/acme-report",
        ),
        claim=claim,
        observed_at=datetime.now(timezone.utc),
    ),
]

config = OmneumClientConfig.from_local_deployment()
server = StdioServerParameters(command="omneum-server")

async with open_stdio_client(config, server) as client:
    evaluation = await client.evaluate_context(observations)
```

A `Source` identifies each retrieved document. The `Claim` represents the value those documents report, and each `Observation` records one source supplying that claim.

`evaluate_context()` evaluates the observations together and returns a `ContextEvaluation` containing the resulting context-quality signals.

### Inspecting the evaluation

Omneum can render the evaluation in a human-readable form:

```python
from omneum import explain_evaluation

print(explain_evaluation(evaluation))
```

The returned `ContextEvaluation` is also available directly to application code, allowing the agent to use Omneum's scores and detected conflicts when deciding what context to pass to the model.

[Python SDK →](docs/sdk.md)

## Integrations

Use Omneum with the framework your agent already runs on:

- [LangGraph](examples/langgraph/)
- [LlamaIndex](examples/llamaindex/)
- [CrewAI](examples/crewai/)
- [OpenAI Agents SDK](examples/openai_agents/)
- [Microsoft Agent Framework](examples/microsoft_agent_framework/)

For a complete framework-independent workflow, see the
[enterprise policy example](examples/enterprise/).

## Core Concepts

### Observations

Context rarely arrives as just a value. A retrieved result also has a source, and often some useful structure around how that source got its information. Omneum keeps those pieces together in an **observation** instead of flattening them into text before evaluation.

Each `Observation` records a source supplying a specific claim:

```python
Observation(
    observation_id="obs-1",
    source=Source(
        kind="web_document",
        identifier="https://example.com/acme-filing",
    ),
    claim=Claim(
        entity_namespace="company",
        entity="Acme",
        attribute="revenue_2025",
        value=4_200_000_000,
    ),
    observed_at=datetime.now(timezone.utc),
)
```

Here, `acme-filing` is the source and `$4.2B` is the value it reports for Acme's 2025 revenue. If the application also knows, for instance, that the document cites another source or was modified at a particular time, that provenance can stay attached to the same observation and not get discarded when the result enters the agent's context.

Timestamps also give Omneum a way to reason about freshness. If an agent retrieves an older database record alongside a newer update for the same field, Omneum can preserve that ordering in the evaluation instead of treating both values as equally current.

```python
Observation(
    observation_id="obs-2",
    source=article,
    claim=revenue_claim,
    observed_at=retrieved_at,
    source_modified_at=published_at,
    cited_sources=(filing,),
    upstream_sources=(filing,),
)
```

This distinction is crucial once the information starts travelling through a system. A filing might report `$4.2B`, several articles repeat it, and a database later ingests one of those articles. An agent can retrieve all of them as separate results, but Omneum still has the structure needed to determine that their agreement may trace back to the same place.

Observations are immutable records of what the application encountered; Omneum evaluates them together instead of merging them into a single canonical "truth". Missing provenance is fine too — the evaluator uses the structure that is available.

### Sources and Claims

Every observation connects a `Source` to a `Claim`.

```python
source = Source(
    kind="web_document",
    identifier="https://example.com/acme-filing",
)

claim = Claim(
    entity_namespace="company",
    entity="Acme",
    attribute="revenue_2025",
    value=4_200_000_000,
)
```

For a RAG pipeline, the source might be a retrieved document; elsewhere it could be a file, API result, database record, or memory record. The identifier gives Omneum a stable way to recognize that source across observations.

Claims capture the specific value a source supplied. Because the entity and attribute are represented explicitly, Omneum can recognize when different sources are talking about the same thing but reporting different values:

```python
Claim(
    entity_namespace="company",
    entity="Acme",
    attribute="revenue_2025",
    value=4_200_000_000,
)

Claim(
    entity_namespace="company",
    entity="Acme",
    attribute="revenue_2025",
    value=3_900_000_000,
)
```

Both claims refer to Acme's 2025 revenue, but they disagree on the value. That disagreement remains part of the context Omneum evaluates instead of being buried inside two text chunks and left for the model to notice later.

### Source Dependence

Counting retrieved results is easy. Figuring out how many independent sources they actually represent is considerably more challenging.

Say we have four sources that all report the same number:

```text
annual-report.pdf ─────────────────────┐
                                      │
article-a.html ── annual-report.pdf ───┤
article-b.html ── annual-report.pdf ───┼── $4.2B
database-row ──── article-a.html ──────┘
```


Before graph evaluation, Omneum uses the provenance available on the observations to estimate relationships between sources. The raw number of supporting sources and the estimated amount of independent support can therefore be different:

```text
Supporting sources:             4
Estimated independent support:  1.6
```

This matters anywhere information gets copied or derived across systems. A RAG index can contain several versions of the same underlying material, news articles can share an original report, and database records can be populated from the same upstream feed. Omneum keeps those relationships in the evaluation, avoiding the common assumption that every source identifier represents a fresh confirmation.

### ContextEvaluation

Calling `evaluate_context()` returns a `ContextEvaluation`:

```python
evaluation = await client.evaluate_context(observations)
```

This is the result your application gets back from Omneum. It brings together claim support and source reliability scores with estimated independent support, detected conflicts, freshness, and information about the source-dependency analysis behind the evaluation.

Those signals describe different problems with context that can otherwise look identical after retrieval. Five documents might support the same value while providing much less independent support because several trace back to the same place; two sources might disagree because one contains an older value that has since been updated. `ContextEvaluation` preserves those differences instead of collapsing context quality into a single score.

What happens next is deliberately left to the application. A RAG pipeline might use the evaluation to choose which results fit into the next model input, while an agent that finds conflicting values might query another source before continuing. Omneum evaluates the context; it doesn't dictate the agent's control flow.

For debugging or inspection, the same evaluation can be rendered in a human-readable form:

```python
from omneum import explain_evaluation

print(explain_evaluation(evaluation))
```

### ContextMapper

Most applications already have their own objects for retrieved context, and rewriting them around Omneum's types would obviously be unnecessary.

A RAG pipeline might already produce something like:

```python
retrieved = [
    {
        "id": "result-1",
        "url": "https://example.com/acme-results",
        "company": "Acme",
        "field": "revenue_2025",
        "value": 4_200_000_000,
        "retrieved_at": datetime.now(timezone.utc),
        "citations": [
            {
                "kind": "web_document",
                "identifier": "https://example.com/acme-filing",
            }
        ],
    }
]
```

`ContextMapper` describes how those existing fields map into Omneum:

```python
from omneum import ContextMapper, Source

mapper = ContextMapper(
    source=lambda item: Source(
        kind="web_document",
        identifier=item["url"],
    ),
    entity_namespace=lambda item: "company",
    entity="company",
    attribute="field",
    value="value",
    observation_id="id",
    observed_at="retrieved_at",
    cited_sources="citations",
)

evaluation = await client.evaluate_mapped(retrieved, mapper)
```

The application keeps its existing schema. The mapper extracts the fields Omneum needs to construct observations, including any provenance already attached to the application's retrieval results, and `evaluate_mapped()` sends those observations through the same evaluation path as `evaluate_context()`.

This is usually the cleaner integration for an existing RAG or agent pipeline: the structure already present in retrieval results doesn't have to be flattened into text or manually rebuilt just to run an evaluation.

[Python SDK ->](docs/sdk.md)

## Performance & Accuracy


## Production

Omneum uses SQLite as its default local storage backend. PostgreSQL is supported for deployments that use an external database.

| Component | Implementation |
|---|---|
| **MCP server** | Local `omneum-server` process |
| **Evaluator** | Managed local daemon |
| **Local database** | SQLite |
| **Graph model** | Relational source, claim, observation, and dependency tables |
| **External database** | PostgreSQL |
| **Graph extension** | Apache AGE |
| **Service manager** | `launchd` on macOS; systemd on Ubuntu |
| **Cryptography** | RFC 9497 VOPRF, Ristretto255-SHA512 |

Local installations create `context.db` automatically:

```text
macOS
~/Library/Application Support/Omneum/context.db

Linux
~/.local/share/omneum/context.db
```

PostgreSQL can be configured for deployments that use an external database. Apache AGE provides the graph projection for PostgreSQL deployments.

See [`docs/storage.md`](docs/storage.md) for the storage schema and deployment options.

## Security & Privacy

Omneum evaluates context locally. `omneum-server`, the evaluator daemon, and `context.db` run on the user's machine.

| Component | Boundary |
|---|---|
| **Context** | Passed to the local evaluation path |
| **Context graph** | Stored in local `context.db` |
| **VOPRF private key** | Held by the evaluator daemon |
| **MCP process** | Cannot read the evaluator's private key |
| **Source payloads** | Not required in the graph |
| **Omneum Network** | Optional contribution through the ingestion API |

Omneum persists the local context graph across MCP sessions.

```text
application data
      │
      ▼
  omneum-server
      │
      ├── evaluator daemon
      │
      └── context.db
```

Local persistence and Omneum Network contribution are configured independently.

| Option | Behavior |
|---|---|
| **Local persistence** | Writes observations to `context.db` |
| **Network contribution** | Sends pseudonymous observations to the Omneum Network through the ingestion API |

See [`docs/context-graph.md`](docs/context-graph.md) for Context Graph contribution and [`docs/storage.md`](docs/storage.md) for storage configuration.

## External Evaluations

External evaluations are published with the test inputs and Omneum outputs in [`evaluations/`](evaluations/).

**SearchTS.** SearchTS 0.13.0 returned the same Go 1.22 claim from `thenewstack.io` through `curl_cffi` and `go.dev` through `stealth-browser`. Omneum received the original `final_url` and `fetched_at` values for both captures. The evaluation returned `2.00` estimated independent support, pairwise dependency `0.0000`, and dependency-signal coverage `0.25`. [Results →](evaluations/searchts/)

**Bastra Recall.** Recall ran Omneum 1.0.3 `dependency-estimator-v4` against a 30-memory synthetic harness. Four memories sharing one upstream source collapsed to `1.0` effective independent support; three independent sources remained at `3.0`. A temporal-only sweep moved continuously from `2.5` effective sources at identical timestamps to `3.0` at 48 hours. The evaluation also exposed an open lineage-chain case where `v1 → v2 → v3 → v4` produces `1.6` rather than `1.0` because dependency is currently computed only across direct lineage edges. [Results →](evaluations/bastra-recall/)

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

If you find a security issue, please follow the private reporting process in [SECURITY.md](SECURITY.md) instead of opening a public issue.

## License

Omneum is open source under the [MIT License](LICENSE).