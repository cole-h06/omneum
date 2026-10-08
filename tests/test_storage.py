"""Run integration tests with OMNEUM_TEST_POSTGRES_DSN pointing at 001 + 002."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import json
import os
import subprocess
import sys

import pytest

from omneum import Claim, LinkageToken, Observation, Source
from omneum.client import VOPRF_MODE
from omneum.linkage import LinkagePurpose
from omneum.storage import PostgresStorage


@pytest.fixture
def db():
    dsn = os.environ.get("OMNEUM_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set OMNEUM_TEST_POSTGRES_DSN to an isolated migrated database")
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(dsn, autocommit=True) as connection:
        yield connection


@pytest.fixture
def workspace(db):
    # All data lives in the explicitly supplied disposable test database.
    organization = db.execute("INSERT INTO public.organizations(name) VALUES ('test') RETURNING id").fetchone()[0]
    return db.execute("INSERT INTO public.workspaces(organization_id,name) VALUES (%s,'test') RETURNING id", (organization,)).fetchone()[0]


def token(purpose, value=1):
    # Fixed opaque test vectors, not an alternative production identity scheme.
    return LinkageToken("urn:uuid:8d96fc18-f40f-4ec7-8ae8-f3711d88b741", 1,
                        VOPRF_MODE, "ristretto255-SHA512", 1, purpose, bytes([value]) * 64)


def persist(db, workspace, source=1, claim=2):
    return PostgresStorage(db).persist_observation(
        workspace_id=workspace,
        observation=Observation("local-id", Source("url", "private-source' $$"),
                                Claim("test", "entity", "attribute", "private-value"),
                                datetime(2026, 1, 1, tzinfo=timezone.utc),
                                metadata={"private": "' $$ private-metadata"}),
        source_token=token(LinkagePurpose.SOURCE, source),
        claim_token=token(LinkagePurpose.CLAIM, claim),
    )


def query_graph(db):
    db.execute("LOAD 'age'")
    db.execute("SET search_path = ag_catalog, public")
    rows = db.execute("""SELECT * FROM cypher('omneum_context', $$
        MATCH (s:Source)-[o:OBSERVED]->(c:Claim)
        RETURN properties(s), properties(o), properties(c)
    $$) AS (s agtype, o agtype, c agtype)""").fetchall()
    return [tuple(json.loads(value) for value in row) for row in rows]


def test_source_claim_and_occurrence_identity(db, workspace):
    first = persist(db, workspace)
    second = persist(db, workspace)
    assert first.source_id == second.source_id
    assert first.claim_id == second.claim_id
    assert first.observation_id != second.observation_id
    assert persist(db, workspace, claim=3).source_id == first.source_id
    assert persist(db, workspace, source=4).claim_id == first.claim_id
    assert db.execute("SELECT source_token FROM public.sources WHERE id=%s", (first.source_id,)).fetchone()[0] == token(LinkagePurpose.SOURCE).value
    assert db.execute("SELECT claim_token FROM public.claims WHERE id=%s", (first.claim_id,)).fetchone()[0] == token(LinkagePurpose.CLAIM, 2).value
    assert db.execute("SELECT count(*) FROM public.observations WHERE workspace_id=%s", (workspace,)).fetchone()[0] == 4
    projected = [r for r in query_graph(db) if r[0]["workspace_id"] == str(workspace)]
    assert len(projected) == 4
    for s, o, c in projected:
        assert set(s) == set(o) == set(c) == {"id", "workspace_id"}
    assert any(o["id"] == str(first.observation_id) and s["id"] == str(first.source_id)
               and c["id"] == str(first.claim_id) for s, o, c in projected)
    for label, expected in (("Source", first.source_id), ("Claim", first.claim_id)):
        # Labels are fixed test constants; all application data is bound.
        query = "SELECT * FROM cypher('omneum_context', $$ MATCH (n:" + label + ") WHERE n.id = $id RETURN count(n) $$, %s::agtype) AS (n agtype)"
        assert db.execute(query, (json.dumps({"id": str(expected)}),), prepare=True).fetchone()[0] == "1"



def test_workspace_isolation(db, workspace):
    other = db.execute("INSERT INTO public.workspaces(organization_id,name) SELECT organization_id,'other' FROM public.workspaces WHERE id=%s RETURNING id", (workspace,)).fetchone()[0]
    a, b = persist(db, workspace), persist(db, other)
    assert a.source_id != b.source_id and a.claim_id != b.claim_id
    import psycopg
    for source_id, claim_id in ((a.source_id, b.claim_id), (b.source_id, a.claim_id)):
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            with db.transaction():
                oid = db.execute("INSERT INTO public.observations(workspace_id,source_id) VALUES (%s,%s) RETURNING id", (workspace, source_id)).fetchone()[0]
                db.execute("INSERT INTO public.assertion_observations VALUES (%s,%s)", (oid, claim_id))


def test_projection_failure_rolls_back_everything(db, workspace, monkeypatch):
    from omneum.storage import graph
    original = graph.project_observation
    def fail(cursor, **kwargs):
        original(cursor, **kwargs)
        cursor.execute("SELECT 1/0")
    monkeypatch.setattr(graph, "project_observation", fail)
    import psycopg
    with pytest.raises(psycopg.errors.DivisionByZero):
        persist(db, workspace)
    for table in ("sources", "claims", "observations"):
        assert db.execute(f"SELECT count(*) FROM public.{table} WHERE workspace_id=%s", (workspace,)).fetchone()[0] == 0
    assert not [r for r in query_graph(db) if r[0]["workspace_id"] == str(workspace)]


def test_caller_transaction_remains_in_control(db, workspace):
    with db.transaction():
        result = persist(db, workspace)
        assert result.observation_id
        db.execute("SET CONSTRAINTS ALL IMMEDIATE")
        # Roll back the outer transaction, including the released savepoint.
        import psycopg
        raise psycopg.Rollback()
    assert not [r for r in query_graph(db) if r[0]["workspace_id"] == str(workspace)]


def test_concurrent_identity_reuse(db, workspace):
    import psycopg
    def write(_):
        with psycopg.connect(os.environ["OMNEUM_TEST_POSTGRES_DSN"], autocommit=True) as conn:
            return persist(conn, workspace)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(write, range(4)))
    assert len({r.source_id for r in results}) == len({r.claim_id for r in results}) == 1
    assert len([r for r in query_graph(db) if r[0]["workspace_id"] == str(workspace)]) == 4


def test_without_postgres_extra():
    script = '''
import importlib.abc
import sys
class NoPostgres(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname == "psycopg" or fullname.startswith("psycopg."):
            raise ModuleNotFoundError("postgres extra deliberately unavailable")
sys.meta_path.insert(0, NoPostgres())
import omneum
import omneum.storage
import omneum.tools.evaluate_context
import pytest
sys.exit(pytest.main(["-q", "tests/test_evaluate_context.py", "tests/test_mcp.py"]))
'''
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_migrations_from_clean_database(db):
    from psycopg import connect, sql
    from psycopg.conninfo import make_conninfo
    name = "omneum_migration_test_" + uuid4().hex
    db.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name)))
    dsn = make_conninfo(os.environ["OMNEUM_TEST_POSTGRES_DSN"], dbname=name)
    root = Path(__file__).resolve().parents[1]
    try:
        result = subprocess.run(
            ["psql", "-X", "--dbname", dsn, "-v", "ON_ERROR_STOP=1",
             "-f", str(root / "migrations/001_initial_schema.sql"),
             "-f", str(root / "migrations/002_context_graph.sql"),
             "-f", str(root / "migrations/002_context_graph.sql"),
             "-f", str(root / "migrations/003_evaluation_history.sql"),
             "-f", str(root / "migrations/003_evaluation_history.sql"),
             ],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        with connect(dsn, autocommit=True) as clean:
            org = clean.execute("INSERT INTO public.organizations(name) VALUES ('migration') RETURNING id").fetchone()[0]
            ws = clean.execute("INSERT INTO public.workspaces(organization_id,name) VALUES (%s,'migration') RETURNING id", (org,)).fetchone()[0]
            source = clean.execute("INSERT INTO public.sources(workspace_id,source_token) VALUES (%s,%s) RETURNING id", (ws, b's'*64)).fetchone()[0]
            claim = clean.execute("INSERT INTO public.claims(workspace_id,claim_token) VALUES (%s,%s) RETURNING id", (ws, b'c'*64)).fetchone()[0]
            oid = clean.execute("INSERT INTO public.observations(workspace_id,source_id,claim_id,metadata) VALUES (%s,%s,%s,'{\"keep\":true}') RETURNING id", (ws,source,claim)).fetchone()[0]
            before = clean.execute('SELECT source_id, observed_at, metadata, created_at FROM public.observations WHERE id=%s', (oid,)).fetchone()
            clean.execute((root / 'migrations/004_observation_subtypes.sql').read_text())
            orphan = clean.execute('INSERT INTO public.observations(workspace_id,source_id) VALUES (%s,%s) RETURNING id', (ws,source)).fetchone()[0]
            import psycopg
            with pytest.raises(psycopg.errors.CheckViolation, match='missing subtype rows'):
                try:
                    clean.execute((root / 'migrations/005_assertion_subtype_integrity.sql').read_text())
                finally:
                    clean.rollback()
            assert clean.execute('SELECT 1 FROM public.observations WHERE id=%s', (orphan,)).fetchone()
            clean.execute('INSERT INTO public.assertion_observations VALUES (%s,%s)', (orphan,claim))
            for _ in range(2):
                clean.execute((root / 'migrations/004_observation_subtypes.sql').read_text())
                clean.execute((root / 'migrations/005_assertion_subtype_integrity.sql').read_text())
            assert clean.execute('SELECT source_id, observed_at, metadata, created_at FROM public.observations WHERE id=%s', (oid,)).fetchone() == before
            assert clean.execute('SELECT observation_type, claim_id FROM public.assertion_observation_envelopes WHERE id=%s', (oid,)).fetchone() == ('assertion', claim)
            assert clean.execute("SELECT count(*) FROM ag_catalog.ag_graph WHERE name='omneum_context'").fetchone()[0] == 1
            labels = clean.execute("""
                SELECT l.name, l.kind, count(*) FROM ag_catalog.ag_label l
                JOIN ag_catalog.ag_graph g ON g.graphid=l.graph
                WHERE g.name='omneum_context' AND l.name IN ('Source','Claim','OBSERVED','DEPENDENT')
                GROUP BY l.name,l.kind
            """).fetchall()
            assert sorted(labels) == [("Claim", "v", 1), ("DEPENDENT", "e", 1), ("OBSERVED", "e", 1), ("Source", "v", 1)]
    finally:
        db.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


def test_assertion_subtypes_and_future_exclusion(db, workspace):
    import psycopg
    row = persist(db, workspace)
    assert db.execute("SELECT observation_type,claim_id FROM public.assertion_observation_envelopes WHERE id=%s",
        (row.observation_id,)).fetchone() == ('assertion', row.claim_id)
    assert not db.execute("SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='observations' AND column_name='claim_id'").fetchone()
    future = db.execute("INSERT INTO public.observations(workspace_id,source_id,observation_type) VALUES (%s,%s,'measurement') RETURNING id",
        (workspace, row.source_id)).fetchone()[0]
    assert not db.execute("SELECT 1 FROM public.assertion_observation_envelopes WHERE id=%s", (future,)).fetchone()
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        db.execute("INSERT INTO public.assertion_observations VALUES (%s,%s)", (future, row.claim_id))
    for oid, cid in ((uuid4(), row.claim_id), (future, uuid4())):
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            db.execute("INSERT INTO public.assertion_observations VALUES (%s,%s)", (oid, cid))
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("UPDATE public.observations SET observation_type='future' WHERE id=%s", (row.observation_id,))
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("UPDATE public.assertion_observations SET claim_id=%s WHERE observation_id=%s", (row.claim_id, row.observation_id))
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute('DELETE FROM public.assertion_observations WHERE observation_id=%s', (row.observation_id,))
    from omneum.storage import graph
    with db.cursor() as cursor:
        with pytest.raises(ValueError, match='valid assertion'):
            graph.project_observation(cursor, workspace_id=workspace, source_id=row.source_id,
                claim_id=row.claim_id, observation_id=future)
    with db.transaction():
        db.execute('DELETE FROM public.observations WHERE id=%s', (row.observation_id,))
        assert not db.execute('SELECT 1 FROM public.assertion_observations WHERE observation_id=%s', (row.observation_id,)).fetchone()
        raise psycopg.Rollback()


def test_direct_sql_assertion_constraint_at_commit(db, workspace):
    import psycopg
    row = persist(db, workspace)
    with pytest.raises(psycopg.errors.CheckViolation, match='requires an assertion subtype'):
        db.execute('INSERT INTO public.observations(workspace_id,source_id) VALUES (%s,%s)', (workspace, row.source_id))
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.transaction():
            oid = db.execute('INSERT INTO public.observations(workspace_id,source_id) VALUES (%s,%s) RETURNING id', (workspace,row.source_id)).fetchone()[0]
            assert db.execute('SELECT 1 FROM public.observations WHERE id=%s', (oid,)).fetchone()
    assert not db.execute('SELECT 1 FROM public.observations WHERE id=%s', (oid,)).fetchone()
    with db.transaction():
        with db.transaction():
            oid = db.execute('INSERT INTO public.observations(workspace_id,source_id) VALUES (%s,%s) RETURNING id', (workspace,row.source_id)).fetchone()[0]
        db.execute('INSERT INTO public.assertion_observations VALUES (%s,%s)', (oid,row.claim_id))
        db.execute('SET CONSTRAINTS ALL IMMEDIATE')
    assert db.execute('SELECT claim_id FROM public.assertion_observation_envelopes WHERE id=%s', (oid,)).fetchone() == (row.claim_id,)
    with db.transaction():
        temporary = db.execute('INSERT INTO public.observations(workspace_id,source_id) VALUES (%s,%s) RETURNING id', (workspace,row.source_id)).fetchone()[0]
        db.execute('DELETE FROM public.observations WHERE id=%s', (temporary,))
    future = db.execute("INSERT INTO public.observations(workspace_id,source_id,observation_type) VALUES (%s,%s,'event') RETURNING id", (workspace,row.source_id)).fetchone()[0]
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        db.execute('INSERT INTO public.assertion_observations VALUES (%s,%s)', (future,row.claim_id))
    with pytest.raises(psycopg.errors.CheckViolation, match='truncate'):
        db.execute('TRUNCATE public.assertion_observations')
    assert db.execute('SELECT 1 FROM public.assertion_observations WHERE observation_id=%s', (oid,)).fetchone()
