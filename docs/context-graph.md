# Context Graph

The Context Graph is Omneum's persistent observation layer. Evaluations consume observations that can be retained across runs and associated with existing sources and claims.

Local installations persist the graph to SQLite by default. Persistence can be disabled per client or evaluation. PostgreSQL is available as an external storage backend.

## Observations

Evaluated context is recorded as **observations**. An observation represents one occurrence of information from a source and carries the provenance available for that occurrence.

Omneum currently supports **assertion observations**. The Python model defines an observation as:

```python
@dataclass(frozen=True, slots=True)
class Observation:
    observation_id: str
    source: Source
    claim: Claim
    observed_at: datetime
    source_modified_at: datetime | None = None
    upstream_sources: tuple[SourceReference, ...] | None = None
    cited_sources: tuple[SourceReference, ...] | None = None
    parent_observation_ids: tuple[str, ...] | None = None
    retrievals: tuple[Retrieval, ...] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    dependency_signals: dict[str, Any] = field(default_factory=dict)

    observation_type: str = "assertion"
```

The implementation lives in [`omneum/information.py`](../omneum/information.py). `observation_type` currently accepts only `assertion`.

Applications can construct assertion observations with `omneum.observations.observe()`:

```python
from datetime import datetime, timezone

from omneum.information import Source
from omneum.observations import observe

observation = observe(
    observation_id="obs-1",
    source=Source(
        kind="web_document",
        identifier="https://example.com/report",
    ),
    entity_namespace="example",
    entity="company",
    attribute="revenue",
    value=100,
    observed_at=datetime.now(timezone.utc),
)
```

`observe()` constructs the corresponding `Claim` and returns an `Observation`.

```text
Source ──► Observation ──► Claim
```

Observations are immutable after persistence. SQLite enforces this with the `observations_immutable` trigger. Assertion-to-claim records have their own update and delete guards.

The schema is defined in [`omneum/storage/schema.py`](../omneum/storage/schema.py).

## Sources & Claims

**Sources** identify where observed information came from. **Claims** represent units of information attributed to those sources.

The public models are defined in `omneum/information.py`:

```python
@dataclass(frozen=True, slots=True)
class Source:
    kind: str
    identifier: str
    owner_id: str | None = None
```

A claim is represented by an entity, attribute and value within an entity namespace:

```python
Claim(
    entity_namespace="example",
    entity="company",
    attribute="revenue",
    value=100,
)
```

Claim values are canonicalized and serialized with RFC 8785 before identity processing.

Sources and claims have persistent identities in the Context Graph. The SQLite schema places uniqueness constraints on their linkage tokens:

```sql
UNIQUE (workspace_id, deployment_id, key_version, source_token)
```

and:

```sql
UNIQUE (workspace_id, deployment_id, key_version, claim_token)
```

Multiple observations can therefore reference the same persisted source or claim.

```text
Source A ──► Observation A ──┐
                             ├──► Claim
Source B ──► Observation B ──┘
```

Each occurrence remains a separate observation with its own provenance.

## Provenance

Assertion observations accept provenance directly through the Python API.

```python
observation = observe(
    ...,
    source_modified_at=modified_at,
    upstream_sources=(upstream,),
    cited_sources=(citation,),
    parent_observation_ids=("obs-parent",),
    retrievals=(retrieval,),
)
```

`upstream_sources` and `cited_sources` contain `SourceReference` values:

```python
from omneum.observations import reference

upstream = reference(
    kind="web_document",
    identifier="https://example.com/source",
)
```

Retrieval provenance uses the `Retrieval` model:

```python
from omneum.observations import retrieval

record = retrieval(
    retrieval_id="retrieval-1",
    kind="document",
    resource_id="document-42",
    retrieved_at=timestamp,
)
```

SQLite stores these records separately from the observation envelope:

```text
observations
├── observation_source_references
├── observation_parents
└── observation_retrievals
```

`observation_source_references.relationship` is restricted to `upstream` or `citation`.

Parent records preserve both the evaluation-local parent ID and the persisted observation ID when the parent can be resolved:

```text
observation_parents
├── local_parent_id
└── parent_observation_id
```

This allows an observation to retain the provenance supplied at evaluation time after it has been persisted.

## Observation Types

The storage model separates the base observation from type-specific data.

```text
observations
     │
     ▼
assertion_observations
     │
     ▼
claims
```

`observations` contains the common observation envelope. `assertion_observations` contains the claim associated with an assertion:

```sql
CREATE TABLE assertion_observations (
    observation_id TEXT PRIMARY KEY
        REFERENCES observations (id) ON DELETE CASCADE,
    claim_id TEXT NOT NULL
        REFERENCES claims (id)
);
```

The database requires assertion subtype records to reference an observation whose `observation_type` is `assertion`.

```sql
WHERE o.id = NEW.observation_id
  AND o.observation_type = 'assertion'
```

The current Python `Observation` DTO only exposes assertion observations. The generic storage envelope leaves room for additional observation types.

The subtype migration is bundled in `omneum/storage/schema.py` for SQLite and in [`migrations/004_observation_subtypes.sql`](../migrations/004_observation_subtypes.sql) for PostgreSQL.

## Source Dependencies

Omneum computes **source dependencies** from provenance available during an evaluation. Each dependency represents an estimated relationship between a pair of sources.

Persisted dependencies contain the source pair and dependency result:

```text
source_dependencies
├── evaluation_run_id
├── source_a_id
├── source_b_id
├── dependency_score
├── signal_coverage
└── components
```

The SQLite schema stores each pair in canonical order:

```sql
CHECK (source_a_id < source_b_id)
```

with one record per pair per evaluation:

```sql
PRIMARY KEY (
    evaluation_run_id,
    source_a_id,
    source_b_id
)
```

The dependency estimator currently supports structural signals for upstream lineage, citations, assertion lineage, ownership, temporal proximity, graph structure and retrieval overlap.

The estimator is implemented in [`omneum/dependency.py`](../omneum/dependency.py).

## Local Persistence

SQLite is the default persistence backend.

`omneum.paths.get_context_db_path()` resolves the database location:

```text
macOS
~/Library/Application Support/Omneum/omneum.db

Linux
~/.local/share/omneum/omneum.db
```

For a new default graph with unsafe data-directory ancestors, Omneum uses
`~/.omneum/data/omneum.db`. Existing graphs and explicit paths are never
silently relocated; shared directory permissions are preserved.

Linux honors an absolute `XDG_DATA_HOME`:

```text
$XDG_DATA_HOME/omneum/omneum.db
```

The path resolver is implemented in [`omneum/paths.py`](../omneum/paths.py).

`SQLiteStorage` uses this path when no explicit database path is supplied:

```python
self.path = (
    paths.get_context_db_path()
    if path is None
    else Path(path).expanduser()
).absolute()
```

The implementation is in [`omneum/storage/sqlite.py`](../omneum/storage/sqlite.py).

A persisted local graph contains:

```text
omneum.db
├── sources
├── claims
├── observations
├── assertion_observations
├── observation_source_references
├── observation_parents
├── observation_retrievals
├── source_dependencies
├── evaluation_runs
├── execution_history
├── source_scores
├── claim_scores
├── claim_support_sources
├── claim_conflicts
└── schema_migrations
```

Persistence is enabled by default in the client:

```python
local_persistence: LocalPersistenceConfig | None = _DefaultLocalPersistence.SQLITE
```

Pass `None` to disable it:

```python
client = OmneumClient(
    ...,
    local_persistence=None,
)
```

A custom SQLite database can be supplied through `LocalPersistenceConfig`.

PostgreSQL persistence is implemented by `PostgresStorage` in [`omneum/storage/postgres.py`](../omneum/storage/postgres.py).

[Storage docs →](storage.md)

## Omneum Network

The **Omneum Network** accepts pseudonymous structural contributions from Omneum evaluations. Hosted contribution is currently restricted to approved closed-beta participants.

Network contribution is configured separately from local persistence:

```python
local_persistence=...
network_contribution=...
```

The contribution path builds a separate network representation from the evaluation. It does not serialize the local `Observation`, `Source` or `Claim` objects directly.

This boundary is explicit in [`omneum/contribution/builder.py`](../omneum/contribution/builder.py):

```python
"""Allowlisted structural projection; never serialize local information objects."""
```

The network representation uses dedicated models from [`omneum/contribution/models.py`](../omneum/contribution/models.py).

An observation contribution contains:

```python
class ContributionObservation(_StrictModel):
    source_id: str
    claim_id: str
    observation_type: Literal["assertion"] = "assertion"
    observed_bucket: str | None = None
```

Sources and claims use network linkage tokens:

```python
class ContributionSource(_StrictModel):
    source_id: str
    source_token: str
    source_kind: str
    key_version: int


class ContributionClaim(_StrictModel):
    claim_id: str
    claim_token: str
    key_version: int
```

`build_contribution()` assigns evaluation-local IDs such as:

```text
s00000000
s00000001
c00000000
c00000001
```

and obtains pseudonymous linkage tokens through the Network linkage client.

Dependency contributions use an explicit structural schema. Supported fields include the dependency score, individual dependency signals and typed directional evidence.

```python
class ContributionDependency(_StrictModel):
    source_low_id: str
    source_high_id: str
    dependency_score: float

    upstream_signal: float | None = None
    citation_signal: float | None = None
    assertion_lineage_signal: float | None = None
    ownership_signal: float | None = None
    temporal_signal: float | None = None
    graph_signal: float | None = None
    retrieval_signal: float | None = None
```

Arbitrary application metadata is not accepted by these contribution models.

The completed `EvaluationContribution` is submitted through the configured ingestion endpoint. Local MCP installations do not receive credentials for the Network database.

## Persistence & Contribution

Local persistence and Network contribution are separate client options.

| Local persistence | Network contribution | Behavior |
|---|---|---|
| Default | Off | Persist the Context Graph to local SQLite |
| Disabled | Off | Evaluate without persistent graph state |
| Default | On | Persist locally and submit an eligible Network contribution |
| Disabled | On | Evaluate and submit an eligible Network contribution without local persistence |

Local persistence can be disabled with:

```python
local_persistence=None
```

Network contribution requires an explicit `NetworkContributionConfig`.

[Configuration docs →](guides/configuration.md) · [Storage docs →](storage.md)
