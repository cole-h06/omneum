# Development Context Graph provenance explorer

This experiment reads **only local `omneum_dev`**. PostgreSQL records remain authoritative.
It adds no production migration, permanent graph schema, evaluation, score, Network
contribution, or installed package entry point. BRAID and its dependency estimator are unchanged.

## Run

From the repository root, using the existing development virtual environment:

```sh
.venv/bin/python tools/provenance_explorer/explorer.py populate
.venv/bin/python tools/provenance_explorer/explorer.py check
.venv/bin/python tools/provenance_explorer/explorer.py serve
```

Leave the server running, then open the viewer from another terminal:

```sh
open http://127.0.0.1:8765
```

The fixture is already populated in this workspace's database. Repeating `populate`
returns `inserted_observations: 0`. Stop the server with Ctrl-C. An alternative HTTP
port can be selected with `serve --port 8766`.

The default database connection is `127.0.0.1:5432`, database `omneum_dev`, current OS
username. If needed, supply the same local development connection explicitly:

```sh
.venv/bin/python tools/provenance_explorer/explorer.py serve \
  --dsn 'host=127.0.0.1 port=5432 dbname=omneum_dev user=YOUR_LOCAL_DEV_USER'
```

Remote hosts, other databases, sockets, service configurations, and unsupported DSN
parameters are rejected **before connecting**. A pinned loopback `hostaddr` prevents
ambient libpq routing overrides. Ambient passwords/passfiles are not used. Unset
`PGSERVICE` if present. The HTTP listener binds only `127.0.0.1`, rejects unrelated
Host headers, exposes only fixed GET routes, and uses read-only database connections.

`psycopg` is already available in this workspace. On another development environment,
it can be installed separately without changing the release requirements or lockfile:

```sh
uv pip install --python .venv/bin/python 'psycopg[binary]==3.3.6'
```

Cytoscape.js 3.33.1 is vendored with its MIT license. No CDN is contacted at runtime.
SHA-256 of `vendor/cytoscape.min.js`:
`f55947f3daa3bae53209d4b885c195c157f595c225e508a6b382598d9452d6e2`.

## Existing migration prerequisite

Migration `004_observation_subtypes.sql` was applied to `omneum_dev` after checking
the core tables, AGE graph, workspace identity constraints, evaluation history
constraints, and all six existing assertion linkages. There is no PostgreSQL migration
ledger in this schema; current state was inspected through catalogs and constraints.
Before application, `observations.claim_id` existed; the subtype table/view and
immutability trigger did not. Afterward, all six subtype rows existed and the
reconstructed observation digest was unchanged:
`1868b047de541415588ec6374928b508`.

The populate command checks for the subtype table/view and refuses to run if they
are absent. For a matching local development installation with migrations 001–003
already applied, inspect state before applying the existing migration:

```sh
env -u PGHOST -u PGHOSTADDR -u PGPORT -u PGDATABASE -u PGUSER -u PGPASSWORD \
  -u PGSERVICE -u PGSERVICEFILE -u PGOPTIONS PGPASSFILE=/dev/null \
  psql -X -w 'host=127.0.0.1 port=5432 dbname=omneum_dev' -v ON_ERROR_STOP=1 \
  -c "SELECT current_database(), to_regclass('public.assertion_observations'), to_regclass('public.assertion_observation_envelopes');"
```

If the subtype objects are absent and prerequisites match the audited state:

```sh
env -u PGHOST -u PGHOSTADDR -u PGPORT -u PGDATABASE -u PGUSER -u PGPASSWORD \
  -u PGSERVICE -u PGSERVICEFILE -u PGOPTIONS PGPASSFILE=/dev/null \
  psql -X -w 'host=127.0.0.1 port=5432 dbname=omneum_dev' -v ON_ERROR_STOP=1 \
  -c "DO \$\$ BEGIN IF current_database()<>'omneum_dev' OR host(inet_server_addr()) NOT IN ('127.0.0.1','::1') THEN RAISE EXCEPTION 'local development database required'; END IF; END \$\$;" \
  -f migrations/004_observation_subtypes.sql
```

Do not replay the bootstrap migrations into an existing database. Migration 004
preserves existing UUIDs, metadata, timestamps, and assertion links.

## Dataset and direction

The isolated fixture workspace is `6ea6ee1a-9e76-5cb4-b7c7-b6972c9b0ec0`.
The fixture is `synthetic-water-lineage-v1`; organizations, workspace name,
observation metadata, relationship metadata, source URLs, and claim entity/value
descriptions explicitly identify synthetic data. Web identifiers use `.invalid`;
no source URL is retrieved.

There are **36 sources, 12 claims, 72 assertions, 27 upstream derivations, and
13 citations**. Four sources have no provenance edges. Chains cover survey imports,
sensor calibration, quality review, compliance requirements, weather imports,
forecasting, and published reporting. They share upstream origins where the fixture
explicitly declares reuse; citations provide separate references. Multiple source
kinds use Omneum's existing `internal_service`, `internal_resource`, `database`, and
`web_document` representations. JSON is recorded as a format, not a new source kind.
Claims are assigned according to each source's synthetic subject matter.

Relationship conventions:

| Relationship | Display | Meaning |
|---|---|---|
| Assertion / AGE `OBSERVED` | Gray arrow, source → claim | Persisted assertion subtype links the occurrence to a claim |
| `upstream` | Green arrow, downstream → upstream | Explicit declaration that the downstream source derives information from the upstream source |
| `citation` | Purple dashed arrow, citing → cited | Explicit reference; derivation, endorsement, and trust are not implied |
| AGE `DEPENDENT` / `source_dependencies` | Optional orange dotted line, no arrow | Symmetric estimated dependence; UUID endpoint ordering is not lineage |

The example `JSON gateway → Database registry → Web field report → Web origin
bulletin` has two derivations followed by a citation. Gateway → registry also has
a separately declared citation, so the viewer demonstrates parallel relationship
types. No reciprocal edges or optional cycles are introduced.

No fabricated evaluations are needed. The fixture calls `PostgresStorage.persist_observation()`
and its existing AGE assertion projection. It uses deterministic **synthetic opaque
linkage-token test vectors**, following the repository storage tests; these are not
genuine VOPRF-issued tokens and are never submitted to any network. Timestamp,
descriptors, and provenance declarations are fixed. An advisory transaction lock
serializes repeated population; stored observation keys prevent append-only duplicate
occurrences. Metadata drift fails and rolls back rather than overwriting history.

## Persistence and queries

The PostgreSQL adapter retains `Observation.metadata` but does not retain the typed
upstream/citation fields. The fixture supplies both and explicitly stores its
development declarations under `metadata.omneum_dev_provenance`. Source and claim
display descriptions are also stored there; the adapter leaves the optional source
kind/identifier and claim value columns unset. The inspector shows those actual null
values separately from the display fields taken from observation metadata.

Provenance edges are projected **on read** using PostgreSQL JSON array expansion and
resolved source references in the same workspace. Each edge exposes the exact stored
relationship JSON, full originating observation metadata, observation UUID, JSON
pointer, and separately labeled derived endpoint/direction attributes. This does not
constitute complete production provenance persistence. No provenance cache or second
permanent graph is created. The existing AGE `OBSERVED` projection is queried and
compared with the relational assertion links on every graph load.

Print the exact node, assertion, provenance, dependency, and AGE queries:

```sh
.venv/bin/python tools/provenance_explorer/explorer.py queries
```

The named SQL constants in `explorer.py` are the queries actually executed. SQL `%s`
parameters bind the fixture workspace UUID; the AGE query binds
`{"workspace_id":"6ea6ee1a-9e76-5cb4-b7c7-b6972c9b0ec0"}` as its parameter map.
The UI fetches `/api/graph`; each request queries live database records rather than
a saved graph export. Refresh database reloads those records.

## Viewer choice and limitations

Apache AGE Viewer was checked through its official public implementation:
[graph component](https://github.com/apache/age-viewer/blob/main/frontend/src/components/cytoscape/CypherResultCytoscapeChart.jsx)
and [property footer](https://github.com/apache/age-viewer/blob/main/frontend/src/components/cytoscape/CypherResultCytoscapeFooter.jsx).
It supports element property inspection, including compact nested JSON rendering.
However, Omneum's AGE vertices/edges contain UUID references rather than the relational
observation payloads; the existing inspector does not provide the required formatted
JSON side panel or authoritative observation enrichment. This small local viewer
handles those requirements without installing its frontend/backend stack or copying
metadata permanently into AGE.

This viewer is fixture-scoped, not a general graph administration UI. It does not
recover provenance lost from old observations, normalize arbitrary external citation
formats, reconstruct parent-observation lineage, or infer derivation from citations.
The fixture intentionally creates no dependency estimates or scores; consequently
the symmetric-dependence overlay is empty for this workspace. Existing dependency
edges in other workspaces remain untouched. Uniform BRAID initialization and all
propagation equations remain unchanged.

## Interaction and screenshot

Source nodes are blue with shapes for JSON (rounded rectangle), database (barrel),
webpage (circle), and structured document (rectangle). Claim nodes are gold diamonds.
Nodes are draggable. Scroll to zoom, drag the background to pan, or use the zoom
buttons. The default **Lineage network** shows all 36 sources and 40 directional
provenance edges; claim nodes and assertions are hidden. **Complete Context Graph**
restores all 12 claims and 72 assertions without removing or changing any records.
Estimated dependence remains a separate optional undirected overlay.

The network layout uses the existing Cytoscape force layout on provenance edges only,
then clears collisions between node labels and separates the four independent sources
along the bottom. Starting positions are fixed so refreshes produce a repeatable
layout. Source nodes and labels are larger, derivation/citation arrows are stronger,
and labels are placed on edges where space permits. Selection displays the relationship
type and actual JSON alongside the graph. Organized grid, Connected layout, and
Circle layout remain available, as do citation and edge-label filters. Click
nodes/edges to inspect their actual records. Clear selection restores the full network.

For a clear screenshot with the full source network and selected metadata:

1. Open the viewer at **1440×1080** (the verified capture size).
2. Click **Research screenshot**. It restores the source-only Lineage network view,
   highlights the multi-hop gateway/registry/report/bulletin chain, and selects the
   stored gateway-to-registry derivation edge without zooming away from the full network.
3. The right inspector
   displays **Actual stored relationship JSON**, including the upstream identifier,
   reason, and capture time. Derived projection attributes are labeled separately.
4. Capture the browser window with the source/claim legend and counts visible.

For a more readable chain close-up, use **Highlight example chain**, then click its
green derivation edge or the purple field-report citation. Both parallel gateway-to-
registry edges remain individually selectable. Restore Lineage network to reset positions.

## Validation

```sh
OMNEUM_PROVENANCE_INTEGRATION=1 PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python -m pytest tools/provenance_explorer/test_explorer.py -q -p no:cacheprovider

env -u OMNEUM_TEST_POSTGRES_DSN -u OMNEUM_INGESTION_TEST_ADMIN_DSN \
  PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
  tests/test_storage.py tests/test_storage_evaluation.py tests/test_sqlite_storage.py \
  tests/test_lineage_evidence.py tests/test_observation_subtypes.py \
  tests/test_dependency.py tests/test_engine_graph.py -q -p no:cacheprovider
```

The fixture tests exercise actual development records, concurrent idempotency, drift
rejection, edge direction/types, exact stored inspector metadata, and connection guards.
PostgreSQL integration DSNs are deliberately unset for the existing suite: those
tests create disposable databases and are inappropriate for this experiment's strict
single-database boundary. Use the fixture-specific integration test instead.

Verified in this workspace: **9 fixture tests passed; 123 existing tests passed,
26 skipped**. Pre-existing records outside the synthetic workspace remain at 2 sources,
2 claims, 6 observations, 2 dependencies, and 2 evaluation runs. Their reconstructed
observation digest still matches the pre-migration digest above.

Optional browser verification uses a temporary Playwright harness and the installed
Chrome, without changing the application's dependencies. Start the explorer first:

```sh
npm install --prefix /private/tmp/omneum-provenance-ui-check \
  --no-audit --no-fund --ignore-scripts playwright-core@1.56.1
node tools/provenance_explorer/verify_ui.mjs
```

`CHROME_EXECUTABLE` and `PLAYWRIGHT_MODULE` can override the local verification paths.
Verified at 1440×1080: 36 visible source nodes and 40 provenance edges by default;
the complete-graph toggle restores 48 visible nodes and 112 edges. The research
screenshot has no intersecting source-node/label bounding boxes. Distinct colors,
shapes, arrows, citation styles, actual source/claim clicks, both parallel
gateway/registry edge clicks with exact JSON and direction, filters, zoom, pan,
node dragging, layout changes, and database refresh also passed. The screenshot
action is verified to preserve the exact stored relationship JSON. Example captures:
`/private/tmp/omneum-provenance-ui-check/research-1440.png`, `selected-provenance.png`,
and `selected-chain.png`.
