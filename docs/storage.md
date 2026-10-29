# Storage

Omneum uses SQLite for local persistence and PostgreSQL for external deployments.

## Storage Backends

| Backend | Use | Graph |
|---|---|---|
| SQLite | Default Python SDK persistence | Relational graph tables |
| PostgreSQL + Apache AGE | User-managed PostgreSQL persistence | Relational tables with AGE graph projection |
| PostgreSQL (relational only) | Hosted Omneum Network | Authoritative `network.*` relational tables |

## Local Storage

Local installations use SQLite. The database is created automatically on first use.

### Database Location

| Platform | Path |
|---|---|
| macOS | `~/Library/Application Support/Omneum/omneum.db` |
| Linux | `~/.local/share/omneum/omneum.db` |

For a new default graph with unsafe data-directory ancestors, Omneum uses
`~/.omneum/data/omneum.db`. Existing graphs and explicit paths are never
silently relocated; shared directory permissions are preserved.

On Linux, an absolute `XDG_DATA_HOME` overrides the default data directory:

```text
$XDG_DATA_HOME/omneum/omneum.db
```

### Database Layout

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

### Schema

| Table | Contents |
|---|---|
| `sources` | Source records |
| `claims` | Claim records |
| `observations` | Observation records |
| `assertion_observations` | Assertion-specific claim linkage |
| `observation_source_references` | Observation source references |
| `observation_parents` | Observation parent relationships |
| `observation_retrievals` | Observation retrieval records |
| `source_dependencies` | Pairwise source dependencies |
| `evaluation_runs` | Evaluation history |
| `execution_history` | Completed preparation measurements linked to evaluation runs |
| `source_scores` | Source reliability scores |
| `claim_scores` | Claim support scores |
| `claim_support_sources` | Sources contributing support to a claim |
| `claim_conflicts` | Claim conflict records |
| `schema_migrations` | Applied SQLite schema versions |

Observations are append-only. Sources and claims reuse their persisted IDs across evaluations.

## Graph Storage

The local context graph is stored as relational tables.

```text
sources
   │
   ▼
observations
   │
   ▼
assertion_observations
   │
   ▼
claims

sources ── source_dependencies ── sources
```

Traversal uses SQL joins and recursive CTEs.

No NetworkX pickle, serialized graph, or JSON document is used as the source of truth.

## SQLite

SQLite is included with Python through the standard `sqlite3` module.

Local persistence requires:

- No database server
- No database credentials
- No open database port
- No Docker container
- No PostgreSQL installation

### Journal Mode

Local databases use WAL mode:

```sql
PRAGMA journal_mode=WAL;
```

Foreign-key enforcement is enabled per connection:

```sql
PRAGMA foreign_keys=ON;
```

### Files

A running database may contain SQLite WAL files next to `omneum.db`:

```text
Omneum/
├── omneum.db
├── omneum.db-wal
└── omneum.db-shm
```

`omneum.db-wal` and `omneum.db-shm` are managed by SQLite.

On macOS and Linux the graph directory must be user-owned with mode `0700`.
Database, WAL, SHM and journal files are checked for ownership, regular-file type,
single-link status and unsafe ACLs; owned file permissions are tightened to
`0600`. Existing insecure directory permissions are rejected. Caller-created
ancestor symlinks and `..` paths are unsupported; use canonical paths. Directory
ancestors are validated before creating descendants. Known remote filesystems
are rejected because WAL depends on local locking.

These controls protect against other OS users. They do not isolate the graph
from malicious processes with the same UID or from root. Local storage contains
plaintext assertions and metadata; use OS disk encryption as appropriate.

## Local MCP

The Python SDK opens the local SQLite database by default. The core MCP evaluator processes request-scoped graphs without persistence.

```text
Python SDK client
    │
    ▼
Local persistence adapter
    │
    ▼
omneum.db
```

No persistence configuration is required.

## Sidecar

Python SDK sidecars use the same default database path for the owning OS user.

```text
Agent processes
    │
    ▼
Omneum sidecar
    │
    ▼
omneum.db
```

SQLite WAL mode allows concurrent readers. Writes use `BEGIN IMMEDIATE` transactions to serialize writers across local processes.

The core MCP server does not open this database.

## PostgreSQL

PostgreSQL is supported for deployments that use an external database.

| Component | Implementation |
|---|---|
| Database | PostgreSQL |
| Driver | `psycopg` |
| Storage adapter | `PostgresStorage` |
| Graph extension | Apache AGE |
| Query language | SQL / openCypher |

The PostgreSQL schema stores the same core entities as local SQLite storage:

```text
sources
claims
observations
source_dependencies
evaluation_runs
source_scores
claim_scores
```

## Hosted production storage

`omneum_prod` stores the shared production Context Graph in authoritative
`network.*` relational tables. `control.*` holds enrollment and ingestion
infrastructure, `public.*` requires separate semantic publication authorization,
and `private` is reserved and empty. Authorized contributions arrive through the
Network HTTPS API; private local graphs remain user-controlled.

The hosted migration runner uses the relational `production_*` sequence through
007 and excludes `production_002_context_graph.sql`. DigitalOcean Managed
PostgreSQL does not support AGE in its published extension lists. Production AGE
projection, synchronization and backfill/rebuild are not implemented; the existing
production AGE migration creates labels only. See the [deployment guide](guides/deployment.md#database-layout)
for the current database layout.

The `PostgresStorage` adapter and unprefixed migrations described above and below
are for user-managed local graphs. They target an incompatible `public.*` schema
and must not be applied to `omneum_prod`. The current adapter calls AGE during
persistence, so it requires AGE even though the hosted relational Network path does
not.

## Apache AGE

Apache AGE provides a property-graph projection for user-managed PostgreSQL Context Graph deployments. The current `PostgresStorage` adapter requires AGE during persistence. Hosted Omneum Network storage uses relational PostgreSQL tables without AGE.

```text
PostgreSQL
├── relational schema
│   ├── sources
│   ├── claims
│   ├── observations
│   └── source_dependencies
│
└── Apache AGE
    └── omneum_context
        ├── Source
        ├── Claim
        ├── OBSERVED
        └── DEPENDENT
```

### Graph Schema

| Label | Type | Source |
|---|---|---|
| `Source` | Vertex | `sources` |
| `Claim` | Vertex | `claims` |
| `OBSERVED` | Edge | `observations` |
| `DEPENDENT` | Edge | `source_dependencies` |

```text
(Source)-[:OBSERVED]->(Claim)
(Source)-[:DEPENDENT]-(Source)
```

The relational records are authoritative. The AGE graph can be rebuilt from them.

## Migrations

SQLite and PostgreSQL use separate migration paths.

### SQLite

SQLite migrations are bundled with the Python package in:

```text
omneum/storage/schema.py
```

Applied migration versions and checksums are recorded in `schema_migrations`.

### PostgreSQL

PostgreSQL schema changes use versioned SQL migrations:

```text
migrations/
├── 001_initial_schema.sql
├── 002_context_graph.sql
└── 003_evaluation_history.sql
```

PostgreSQL migrations also create required extensions and AGE graph objects.

## Environments

| Environment | Database | Configuration |
|---|---|---|
| Local MCP | SQLite | Automatic |
| Local sidecar | SQLite | Automatic |
| User-managed deployment | PostgreSQL | Explicit |
| Graph-enabled deployment | PostgreSQL + Apache AGE | Explicit |

## Local Data Boundary

`omneum.db` contains the local context graph.

Local evaluation reads and writes this database. Network contribution uses the Omneum Network ingestion API rather than a direct connection to the Network database.

See [`context-graph.md`](context-graph.md) for Network contribution.

## Requirements

### Local

- Python 3.11–3.14
- SQLite through Python `sqlite3`

### PostgreSQL

- PostgreSQL
- `psycopg`
- Apache AGE when graph projection is enabled
