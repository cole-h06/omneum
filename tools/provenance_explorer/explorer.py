"""Local research tool; deliberately outside the installed omneum package."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha512
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import getpass
import sys
from uuid import UUID, uuid5

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from omneum import Claim, LinkageToken, Observation, Source, SourceReference
from omneum.client import VOPRF_MODE
from omneum.linkage import LinkagePurpose
from omneum.sources import internal_source_id
from omneum.storage import PostgresStorage

HERE = Path(__file__).resolve().parent
NAMESPACE = "omneum_dev_provenance"
FIXTURE = "synthetic-water-lineage-v1"
SCOPE = UUID("d157a296-3b9b-43bc-b3c5-ef0fc90e12ec")
WORKSPACE = uuid5(SCOPE, FIXTURE + ":workspace")
ORGANIZATION = uuid5(SCOPE, FIXTURE + ":organization")
DEPLOYMENT = "urn:uuid:" + str(uuid5(SCOPE, FIXTURE + ":test-token-context"))
STAMP = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)

# Source kinds are supported Omneum kinds. JSON is a format, not a new kind.
SOURCE_SPECS = (
    ("gateway", "JSON gateway", "internal_service", "JSON"),
    ("registry", "Database registry", "database", "database record"),
    ("report", "Web field report", "web_document", "webpage"),
    ("bulletin", "Web origin bulletin", "web_document", "webpage"),
    ("regional", "JSON regional API", "internal_service", "JSON"),
    ("cache", "JSON cached export", "internal_resource", "JSON"),
    ("audit", "Database audit row", "database", "database record"),
    ("shared", "Web shared survey", "web_document", "webpage"),
    ("mirror", "Web survey digest", "web_document", "webpage"),
    ("brief", "Structured brief", "internal_resource", "structured document"),
    ("dataset", "Database dataset", "database", "database record"),
    ("ind-web", "Independent webpage", "web_document", "webpage"),
    ("ind-db", "Independent database", "database", "database record"),
    ("ind-json", "Independent JSON API", "internal_service", "JSON"),
    ("methods", "Web methods note", "web_document", "webpage"),
    ("status", "JSON status API", "internal_service", "JSON"),
    ("sensor-log", "Sensor log record", "database", "database record"),
    ("calibration", "Web calibration sheet", "web_document", "webpage"),
    ("sensor-api", "JSON sensor API", "internal_service", "JSON"),
    ("sensor-export", "Structured sensor export", "internal_resource", "structured document"),
    ("quality-db", "Quality review row", "database", "database record"),
    ("quality-api", "JSON quality API", "internal_service", "JSON"),
    ("standards", "Web measurement standard", "web_document", "webpage"),
    ("compliance", "Compliance checklist", "internal_resource", "structured document"),
    ("compliance-db", "Compliance ledger", "database", "database record"),
    ("compliance-api", "JSON compliance API", "internal_service", "JSON"),
    ("planning-db", "Forecast inputs", "database", "database record"),
    ("forecast-api", "JSON forecast API", "internal_service", "JSON"),
    ("forecast-doc", "Forecast planning brief", "internal_resource", "structured document"),
    ("weather", "Web weather report", "web_document", "webpage"),
    ("weather-db", "Weather import row", "database", "database record"),
    ("weather-api", "JSON weather API", "internal_service", "JSON"),
    ("public-report", "Web public summary", "web_document", "webpage"),
    ("report-export", "Structured report export", "internal_resource", "structured document"),
    ("archive-db", "Report archive row", "database", "database record"),
    ("ind-standard", "Independent lab note", "web_document", "webpage"),
)
CLAIMS = tuple(Claim("service", "Synthetic water station", attribute, value)
               for attribute, value in (("temperature_c", 18), ("capacity_l", 1200),
                   ("sensor_count", 8), ("region", "synthetic-north"),
                   ("sample_date", "2026-10-01"), ("status", "synthetic-operational"),
                   ("calibration_version", "synthetic-v3"), ("quality_flag", "synthetic-reviewed"),
                   ("measurement_unit", "litre"), ("forecast_demand_l", 900),
                   ("rainfall_mm", 12), ("report_period", "synthetic-2026-Q4")))
RELATIONS = (
    ("gateway", "registry", "upstream", "Gateway output is transformed from the registry record."),
    ("gateway", "registry", "citation", "Gateway also explicitly cites the registry record."),
    ("registry", "report", "upstream", "Registry values are imported from the field report."),
    ("report", "bulletin", "citation", "Field report references the earlier bulletin; derivation is not asserted."),
    ("regional", "shared", "upstream", "Regional API transforms the common survey."),
    ("cache", "shared", "upstream", "Cached JSON exports the common survey."),
    ("audit", "shared", "upstream", "Audit record imports the common survey."),
    ("mirror", "shared", "citation", "Digest cites the survey without asserting derivation."),
    ("brief", "regional", "upstream", "Structured brief is generated from the regional API."),
    ("brief", "mirror", "citation", "Brief separately cites the survey digest."),
    ("dataset", "bulletin", "upstream", "Dataset extracts structured values from the bulletin."),
    ("methods", "bulletin", "citation", "Methods note references the bulletin."),
    ("status", "dataset", "upstream", "Status JSON is generated from the dataset."),
    ("status", "methods", "citation", "Status API cites a methods note."),
    ("sensor-log", "calibration", "upstream", "Sensor log imports calibration coefficients from the sheet."),
    ("calibration", "standards", "citation", "Calibration sheet cites the measurement standard."),
    ("sensor-api", "sensor-log", "upstream", "Sensor API serializes logged measurements."),
    ("sensor-export", "sensor-log", "upstream", "Sensor export converts the same log to a structured document."),
    ("quality-db", "sensor-api", "upstream", "Quality row imports sensor measurements for review."),
    ("quality-db", "shared", "citation", "Quality review cites the field survey as comparison context."),
    ("quality-api", "quality-db", "upstream", "Quality API exposes the reviewed database result."),
    ("quality-api", "methods", "citation", "Quality API references the review method."),
    ("compliance", "standards", "upstream", "Checklist requirements are extracted from the standard."),
    ("compliance", "calibration", "citation", "Checklist separately cites the calibration sheet."),
    ("compliance-db", "compliance", "upstream", "Ledger imports checklist requirements."),
    ("compliance-db", "quality-db", "upstream", "Ledger also imports the reviewed quality result."),
    ("compliance-api", "compliance-db", "upstream", "Compliance API transforms the ledger."),
    ("planning-db", "dataset", "upstream", "Forecast inputs import baseline station data."),
    ("planning-db", "weather-db", "upstream", "Forecast inputs also import weather measurements."),
    ("forecast-api", "planning-db", "upstream", "Forecast API computes its output from forecast inputs."),
    ("forecast-api", "quality-api", "citation", "Forecast API cites the quality review for measurement context."),
    ("forecast-doc", "forecast-api", "upstream", "Planning brief summarizes forecast API output."),
    ("forecast-doc", "compliance-api", "citation", "Planning brief references compliance status without importing it."),
    ("weather-db", "weather", "upstream", "Weather row imports the published weather report."),
    ("weather-api", "weather-db", "upstream", "Weather API exposes imported weather measurements."),
    ("public-report", "forecast-doc", "upstream", "Public summary derives its forecast section from the brief."),
    ("public-report", "brief", "upstream", "Public summary derives its survey section from the structured brief."),
    ("public-report", "standards", "citation", "Public summary cites the measurement standard."),
    ("report-export", "public-report", "upstream", "Structured export extracts the public summary."),
    ("archive-db", "report-export", "upstream", "Archive row imports the exported summary."),
)

# Claims reflect each source's declared subject; overlap supplies meaningful assertions.
CLAIM_ASSIGNMENTS = (
    (0,1),(0,1),(0,4),(1,4),(2,3),(2,3),(2,4),(2,3),
    (2,4),(3,5),(1,5),(0,3),(1,2),(0,5),(4,8),(1,5),
    (0,6),(6,8),(0,6),(0,6),(0,7),(0,7),(6,8),(7,8),
    (7,8),(7,8),(1,10),(9,10),(9,11),(4,10),(4,10),(4,10),
    (9,11),(9,11),(9,11),(6,7),
)

SOURCE_QUERY = "SELECT to_jsonb(s) AS stored FROM public.sources s WHERE workspace_id=%s ORDER BY id"
CLAIM_QUERY = "SELECT to_jsonb(c) AS stored FROM public.claims c WHERE workspace_id=%s ORDER BY id"
OBSERVATION_QUERY = """
SELECT to_jsonb(o) AS stored, a.claim_id
FROM public.observations o
JOIN public.assertion_observations a ON a.observation_id=o.id
WHERE o.workspace_id=%s ORDER BY o.id
"""
PROVENANCE_QUERY = """
WITH targets AS (
    SELECT DISTINCT o.source_id, o.metadata->'omneum_dev_provenance'->'source'->>'key' AS key
    FROM public.observations o WHERE o.workspace_id=%s
)
SELECT o.id AS observation_id, o.source_id, t.source_id AS target_id,
       p.ordinality, p.relationship AS stored_relationship
FROM public.observations o
CROSS JOIN LATERAL jsonb_array_elements(
    o.metadata->'omneum_dev_provenance'->'provenance'
) WITH ORDINALITY AS p(relationship, ordinality)
LEFT JOIN targets t ON t.key=p.relationship->'target'->>'key'
WHERE o.workspace_id=%s
ORDER BY o.id, p.ordinality
"""
AGE_QUERY = """
SELECT * FROM ag_catalog.cypher('omneum_context', $$
    MATCH (s:Source)-[o:OBSERVED]->(c:Claim)
    WHERE s.workspace_id=$workspace_id
    RETURN s.id, o.id, c.id
$$, %s::ag_catalog.agtype) AS (source_id ag_catalog.agtype,
    observation_id ag_catalog.agtype, claim_id ag_catalog.agtype)
"""
DEPENDENCY_QUERY = """
SELECT to_jsonb(d) AS stored FROM public.source_dependencies d
WHERE workspace_id=%s ORDER BY evaluation_run_id,source_a_id,source_b_id
"""


def connect(dsn=None, *, readonly=False):
    """Reject other databases/remote hosts BEFORE connecting; ignore libpq defaults."""
    import psycopg
    from psycopg.conninfo import conninfo_to_dict

    config = conninfo_to_dict(dsn or "")
    if set(config) - {"dbname", "host", "port", "user", "password"}:
        raise ValueError("DSN may contain only dbname, host, port, user, password")
    if config.get("dbname", "omneum_dev") != "omneum_dev":
        raise ValueError("Only omneum_dev is permitted")
    if config.get("host", "127.0.0.1") not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("Only a loopback PostgreSQL host is permitted")
    kwargs = dict(dbname="omneum_dev", host="127.0.0.1", port="5432", user=getpass.getuser())
    kwargs.update(config)
    if os.environ.get("PGSERVICE"):
        raise ValueError("Unset PGSERVICE; this tool does not load libpq service configurations")
    # Explicit hostaddr/password prevent ambient PGHOSTADDR/PGPASSWORD from routing
    # this experiment elsewhere or selecting unrelated credentials.
    kwargs["hostaddr"] = "::1" if kwargs["host"] == "::1" else "127.0.0.1"
    kwargs.setdefault("password", "unused-local-development-password")
    connection = psycopg.connect(**kwargs, autocommit=True, connect_timeout=3,
        passfile="/dev/null", sslmode="disable",
        options="-c default_transaction_read_only=" + ("on" if readonly else "off"))
    try:
        db, host = connection.execute("SELECT current_database(), host(inet_server_addr())").fetchone()
        if db != "omneum_dev" or host not in {"127.0.0.1", "::1"}:
            raise ValueError("Connected server must be local omneum_dev")
    except Exception:
        connection.close()
        raise
    return connection


def sources():
    return {key: Source(kind, f"https://synthetic.example.invalid/{key}" if kind == "web_document"
                        else internal_source_id(str(SCOPE), FIXTURE + ":" + key))
            for key, _, kind, _ in SOURCE_SPECS}


def synthetic_token(purpose, key):
    # Explicit synthetic opaque test vectors, following tests/test_storage.py.
    # No cryptographic evaluation or genuine VOPRF issuance is claimed.
    value = sha512(f"{FIXTURE}:{purpose.name}:{key}".encode()).digest()
    return LinkageToken(DEPLOYMENT, 1, VOPRF_MODE, "ristretto255-SHA512", 1, purpose, value)


def fixture_observations():
    source_map = sources()
    specs = {key: (name, kind, fmt) for key, name, kind, fmt in SOURCE_SPECS}
    rows = []
    for index, (key, name, kind, fmt) in enumerate(SOURCE_SPECS):
        relationships = []
        for downstream, upstream, relationship, reason in RELATIONS:
            if downstream != key:
                continue
            target = source_map[upstream]
            relationships.append(dict(synthetic=True, type=relationship,
                target=dict(key=upstream, kind=target.kind, identifier=target.identifier),
                upstream_uri=target.identifier if relationship == "upstream" else None,
                citation_identifier=f"synthetic-citation:{key}:{upstream}" if relationship == "citation" else None,
                evidence=dict(description=reason, captured_at=STAMP.isoformat(),
                              origin="explicit synthetic fixture declaration")))
        for occurrence, claim_index in enumerate(CLAIM_ASSIGNMENTS[index]):
            claim = CLAIMS[claim_index]
            local_key = f"{key}:claim-{claim_index}"
            metadata = {NAMESPACE: dict(synthetic=True, fixture_id=FIXTURE, observation_key=local_key,
                source=dict(key=key, name=name, kind=kind, identifier=source_map[key].identifier, format=fmt),
                claim=dict(key=f"claim-{claim_index}", entity_namespace=claim.entity_namespace,
                           entity=claim.entity, attribute=claim.attribute, value=claim.value),
                provenance=relationships if occurrence == 0 else [])}
            rows.append(Observation(local_key, source_map[key], claim, STAMP,
                upstream_sources=tuple(SourceReference(source_map[u].kind, source_map[u].identifier)
                    for d,u,t,_ in RELATIONS if d == key and t == "upstream"),
                cited_sources=tuple(SourceReference(source_map[u].kind, source_map[u].identifier)
                    for d,u,t,_ in RELATIONS if d == key and t == "citation"), metadata=metadata))
    return tuple(rows)


def require_schema(db):
    found = db.execute("SELECT to_regclass('public.assertion_observations'), "
                       "to_regclass('public.assertion_observation_envelopes')").fetchone()
    if not all(found):
        raise ValueError("Apply existing migration 004_observation_subtypes.sql to omneum_dev first")


def populate(db):
    require_schema(db)
    observations = fixture_observations()
    with db.transaction():
        db.execute("SELECT pg_advisory_xact_lock(%s)", (int.from_bytes(sha512(FIXTURE.encode()).digest()[:7], "big"),))
        db.execute("INSERT INTO public.organizations(id,name) VALUES (%s,%s) ON CONFLICT(id) DO NOTHING",
                   (ORGANIZATION, "SYNTHETIC provenance research"))
        db.execute("INSERT INTO public.workspaces(id,organization_id,name) VALUES (%s,%s,%s) "
                   "ON CONFLICT(id) DO NOTHING", (WORKSPACE, ORGANIZATION, "SYNTHETIC provenance explorer v1"))
        org, name = db.execute("SELECT organization_id,name FROM public.workspaces WHERE id=%s", (WORKSPACE,)).fetchone()
        if (org, name) != (ORGANIZATION, "SYNTHETIC provenance explorer v1"):
            raise ValueError("Fixture workspace identity collision")
        existing = db.execute("SELECT metadata,observed_at FROM public.observations WHERE workspace_id=%s", (WORKSPACE,)).fetchall()
        keys = [m[NAMESPACE]["observation_key"] for m, _ in existing]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate fixture observations detected")
        expected = {o.observation_id: o for o in observations}
        for metadata, timestamp in existing:
            key = metadata[NAMESPACE]["observation_key"]
            if key not in expected or expected[key].metadata != metadata or timestamp != STAMP:
                raise ValueError("Fixture drift detected; no records were changed")
        storage = PostgresStorage(db)
        inserted = 0
        for observation in observations:
            if observation.observation_id in keys:
                continue
            storage.persist_observation(workspace_id=WORKSPACE, observation=observation,
                source_token=synthetic_token(LinkagePurpose.SOURCE, observation.metadata[NAMESPACE]["source"]["key"]),
                claim_token=synthetic_token(LinkagePurpose.CLAIM, observation.metadata[NAMESPACE]["claim"]["key"]))
            inserted += 1
        # Validate within the same transaction; failures roll back the whole fixture.
        result = read_graph(db)
        validate_graph(result)
    return {"inserted_observations": inserted, **result["counts"]}


def read_graph(db):
    require_schema(db)
    with db.transaction():
        source_rows = db.execute(SOURCE_QUERY, (WORKSPACE,)).fetchall()
        claim_rows = db.execute(CLAIM_QUERY, (WORKSPACE,)).fetchall()
        observations = db.execute(OBSERVATION_QUERY, (WORKSPACE,)).fetchall()
        source_descriptions, claim_descriptions, metadata_by_observation = {}, {}, {}
        node_observations = {}
        edges = []
        for stored, claim_id in observations:
            metadata = stored["metadata"]
            if metadata.get(NAMESPACE, {}).get("fixture_id") != FIXTURE:
                raise ValueError("Unexpected data in synthetic workspace")
            annotation = metadata[NAMESPACE]
            source_id, cid = stored["source_id"], str(claim_id)
            for descriptions, node_id, value in ((source_descriptions, source_id, annotation["source"]),
                                                 (claim_descriptions, cid, annotation["claim"])):
                if node_id in descriptions and descriptions[node_id] != value:
                    raise ValueError("Conflicting fixture display metadata")
                descriptions[node_id] = value
                node_observations.setdefault(node_id, []).append(stored)
            metadata_by_observation[stored["id"]] = metadata
            edges.append(dict(data=dict(id=stored["id"], source=source_id, target=cid, type="assertion",
                label="asserts", stored=stored, assertion_subtype={"observation_id": stored["id"], "claim_id": cid},
                derived={"direction": "source → claim", "basis": "assertion_observations claim linkage"})))
        nodes = []
        positions = {key: {"x": (i % 6) * 220, "y": (i // 6) * 170}
                     for i, (key, *_rest) in enumerate(SOURCE_SPECS)}
        for (stored,) in source_rows:
            annotation = source_descriptions[stored["id"]]
            nodes.append(dict(data=dict(id=stored["id"], category="source", label=annotation["name"],
                format=annotation["format"], stored=stored, observations=node_observations[stored["id"]],
                display_metadata=annotation, derived={"label_origin": f"observations.metadata.{NAMESPACE}.source"}),
                position=positions[annotation["key"]]))
        for (stored,) in claim_rows:
            annotation = claim_descriptions[stored["id"]]
            index = int(annotation["key"].split("-")[1])
            nodes.append(dict(data=dict(id=stored["id"], category="claim", label=annotation["attribute"],
                stored=stored, observations=node_observations[stored["id"]], display_metadata=annotation,
                derived={"label_origin": f"observations.metadata.{NAMESPACE}.claim"}),
                position={"x": 1380 + (index % 2) * 210, "y": (index // 2) * 170}))
        for oid, source, target, ordinal, relationship in db.execute(PROVENANCE_QUERY, (WORKSPACE, WORKSPACE)):
            if target is None or relationship["type"] not in {"upstream", "citation"}:
                raise ValueError("Unresolved or unsupported provenance relationship")
            edges.append(dict(data=dict(id=f"{oid}:provenance:{ordinal}", source=str(source), target=str(target),
                type=relationship["type"], label="derived from" if relationship["type"] == "upstream" else "cites",
                stored_relationship=relationship, stored_observation_metadata=metadata_by_observation[str(oid)],
                derived=dict(direction="downstream → upstream" if relationship["type"] == "upstream" else "citing → cited",
                    observation_id=str(oid), metadata_pointer=f"/{NAMESPACE}/provenance/{ordinal-1}",
                    projection="read-time projection from PostgreSQL observation metadata"))))
        # Never infer lineage from DEPENDENT endpoint ordering. These are optional undirected overlays.
        for (stored,) in db.execute(DEPENDENCY_QUERY, (WORKSPACE,)):
            edges.append(dict(data=dict(id=f"dependent:{stored['evaluation_run_id']}:{stored['source_a_id']}:{stored['source_b_id']}",
                source=stored["source_a_id"], target=stored["source_b_id"], type="dependent", label="estimated dependence",
                stored=stored, derived={"direction": "none: symmetric estimated dependence; UUID ordering is not lineage"})))
        db.execute("LOAD 'age'")
        db.execute("SET LOCAL search_path=ag_catalog,pg_catalog,public")
        projected = {tuple(json.loads(v) for v in row) for row in db.execute(AGE_QUERY,
            (json.dumps({"workspace_id": str(WORKSPACE)}),), prepare=True)}
        expected_projection = {(e["data"]["source"], e["data"]["id"], e["data"]["target"])
                               for e in edges if e["data"]["type"] == "assertion"}
        if projected != expected_projection:
            raise ValueError("AGE assertion projection differs from authoritative relational records")
    counts = dict(Counter(e["data"]["type"] for e in edges))
    counts.update(sources=len(source_rows), claims=len(claim_rows), age_assertions=len(projected))
    return dict(database="omneum_dev", fixture_id=FIXTURE, workspace_id=str(WORKSPACE), synthetic=True,
                nodes=nodes, edges=edges, counts=counts)


def validate_graph(result):
    if result["counts"] != dict(sources=36, claims=12, assertion=72, upstream=27, citation=13, age_assertions=72):
        raise ValueError(f"Unexpected fixture counts: {result['counts']}")
    nodes = {n["data"]["id"]: n["data"] for n in result["nodes"]}
    actual = set()
    for edge in result["edges"]:
        data = edge["data"]
        if data["type"] in {"upstream", "citation"}:
            if not nodes[data["source"]]["category"] == nodes[data["target"]]["category"] == "source":
                raise ValueError("Provenance endpoints must both be sources")
            actual.add((nodes[data["source"]]["display_metadata"]["key"],
                        nodes[data["target"]]["display_metadata"]["key"], data["type"]))
            pointer_index = int(data["derived"]["metadata_pointer"].split("/")[-1])
            if data["stored_relationship"] != data["stored_observation_metadata"][NAMESPACE]["provenance"][pointer_index]:
                raise ValueError("Projected metadata differs from the stored relationship")
    if actual != {(d,u,t) for d,u,t,_ in RELATIONS}:
        raise ValueError("Fixture relationship directions or types differ from declarations")


def serve(dsn, port):
    # Preflight before opening the HTTP listener. Each request owns a read-only connection.
    with connect(dsn, readonly=True) as db:
        validate_graph(read_graph(db))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
            if self.headers.get("Host") not in allowed:
                self.send_error(403)
                return
            if self.path == "/api/graph":
                try:
                    with connect(dsn, readonly=True) as db:
                        body = json.dumps(read_graph(db), ensure_ascii=False).encode()
                    content_type = "application/json; charset=utf-8"
                except Exception:
                    self.send_error(503, "Development database query failed; inspect local configuration")
                    return
            elif self.path in {"/", "/index.html", "/vendor/cytoscape.min.js"}:
                path = HERE / ("index.html" if self.path in {"/", "/index.html"} else self.path.lstrip("/"))
                body = path.read_bytes()
                content_type = "text/html; charset=utf-8" if path.suffix == ".html" else "text/javascript"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Synthetic provenance explorer: http://127.0.0.1:{port} (omneum_dev only)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("populate", "check", "serve", "queries"))
    parser.add_argument("--dsn", help="Local omneum_dev DSN; defaults to loopback:5432 and current OS user")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.command == "queries":
        print(f"-- Workspace: {WORKSPACE}\n-- Bind each %s as this workspace UUID; AGE binds a JSON parameter map.")
        for name in ("SOURCE_QUERY", "CLAIM_QUERY", "OBSERVATION_QUERY", "PROVENANCE_QUERY", "DEPENDENCY_QUERY", "AGE_QUERY"):
            print(f"\n-- {name}\n{globals()[name]};")
    elif args.command == "serve":
        serve(args.dsn, args.port)
    else:
        with connect(args.dsn, readonly=args.command == "check") as db:
            if args.command == "populate":
                print(json.dumps(populate(db), indent=2))
            else:
                result = read_graph(db)
                validate_graph(result)
                print(json.dumps(result["counts"], indent=2))


if __name__ == "__main__":
    main()
