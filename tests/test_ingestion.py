"""Production boundary tests; database tests create a fresh disposable database.

Set OMNEUM_INGESTION_TEST_ADMIN_DSN to a local, isolated test cluster. Never use
production credentials. The supplied database name must contain 'test'.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from omneum.base64url import encode_unpadded
from omneum.ingestion import IngestionService
from omneum.ingestion.validation import MAX_BODY_BYTES, MAX_COLLECTION

PRINCIPAL = uuid4()


def payload():
    def token(n):
        return encode_unpadded(bytes([n]) * 64, expected_length=64)
    return dict(
        idempotency_key="test-1", evaluator_version="v2", estimator_version="v4",
        sources=[dict(source_id=f"s{i}", source_token=token(i), source_kind="url", key_version=1)
                 for i in (1, 2)],
        claims=[dict(claim_id="c1", claim_token=token(3), key_version=1)],
        observations=[dict(source_id="s1", claim_id="c1"), dict(source_id="s2", claim_id="c1")],
        source_scores=[dict(source_id="s1", reliability=0.8)],
        claim_scores=[dict(claim_id="c1", support=1.2, supporting_source_count=2,
                           estimated_independent_support_count=1.5)],
        dependencies=[dict(source_low_id="s1", source_high_id="s2", dependency_score=0.3)],
    )


class Auth:
    def authenticate(self, credential):
        return PRINCIPAL if credential == "test-key" else None


def forbidden_connection():
    raise AssertionError("DB must not be accessed")


def service(factory=forbidden_connection, auth=None):
    return IngestionService(authenticator=auth or Auth(), connection_factory=factory,
                            allowed_key_versions=frozenset({1}))


def submit(handler, value=None, authorization="Bearer test-key"):
    return handler.handle(authorization=authorization,
                          body=json.dumps(payload() if value is None else value).encode())


@pytest.mark.parametrize("authorization", [None, "", "Basic test-key", "Bearer invalid", "Bearer ",
                                             "Bearer test-key\n", "Bearer " + "a" * 4096])
def test_auth_rejected(authorization):
    assert submit(service(), authorization=authorization).status == 401


def test_auth_exception_fails_closed():
    class Broken:
        def authenticate(self, credential):
            raise RuntimeError("secret credential")
    assert submit(service(auth=Broken())).code == "unauthorized"


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(workspace_id=str(uuid4())),
    lambda p: p.update(organization_id=str(uuid4())),
    lambda p: p.update(context="secret"),
    lambda p: p.update(metadata={"secret": True}),
    lambda p: p["sources"][0].update(identifier="secret"),
    lambda p: p["claims"][0].update(value="secret"),
    lambda p: p["observations"][0].update(source_id="missing"),
    lambda p: p["observations"][0].update(claim_id="missing"),
    lambda p: p["source_scores"][0].update(source_id="missing"),
    lambda p: p["claim_scores"][0].update(claim_id="missing"),
    lambda p: p["sources"].append(p["sources"][0]),
    lambda p: p["claims"].append(p["claims"][0]),
    lambda p: p["source_scores"].append(p["source_scores"][0]),
    lambda p: p["claim_scores"].append(p["claim_scores"][0]),
    lambda p: p["dependencies"].append(p["dependencies"][0]),
    lambda p: p["dependencies"][0].update(source_high_id="s1"),
    lambda p: p["dependencies"][0].update(source_high_id="missing"),
    lambda p: p["dependencies"][0].update(source_low_id="s2", source_high_id="s1"),
    lambda p: p["sources"][0].update(source_id=""),
    lambda p: p["sources"][0].update(source_token="bad"),
    lambda p: p["sources"][0].update(key_version=0),
    lambda p: p["sources"][0].update(key_version=2),
    lambda p: p["sources"][1].update(source_token=p["sources"][0]["source_token"]),
    lambda p: p["claim_scores"][0].update(supporting_source_count=1),
    lambda p: p["claim_scores"][0].update(estimated_independent_support_count=3.0),
    lambda p: p["claim_scores"][0].update(dependency_cluster_count=3),
    lambda p: p["dependencies"][0].update(signal_components={"signal": float("nan")}),
    lambda p: p["dependencies"][0].update(qualifying_time_deltas_seconds=[float("inf")]),
    lambda p: p["dependencies"][0].update(qualifying_time_deltas_seconds=[1] * 65),
    lambda p: p["observations"][0].update(observed_bucket="2026-01-01T01:23:45Z"),
    lambda p: p.update(idempotency_key="'; DROP TABLE network.sources;--"),
    lambda p: p.update(sources=[p["sources"][0]] * (MAX_COLLECTION + 1)),
])
def test_invalid_semantics_rejected_before_db(mutation):
    p = payload()
    mutation(p)
    assert submit(service(), p).status == 400


@pytest.mark.parametrize("body", [b"{", b"[]", b"null", b'{}', b'{"a":1,"a":2}', b"[" * 10000])
def test_malformed(body):
    assert service().handle(authorization="Bearer test-key", body=body).status == 400


def test_request_size():
    assert service().handle(authorization="Bearer test-key", body=b"x" * (MAX_BODY_BYTES + 1)).status == 413


@pytest.fixture(scope="module")
def database():
    dsn = os.environ.get("OMNEUM_INGESTION_TEST_ADMIN_DSN")
    if not dsn:
        pytest.skip("set an isolated OMNEUM_INGESTION_TEST_ADMIN_DSN")
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    config = conninfo_to_dict(dsn)
    assert "test" in config.get("dbname", "").lower()
    assert config.get("host", "").startswith("/") or config.get("host") in ("localhost", "127.0.0.1")
    name = "omneum_ingestion_test_" + uuid4().hex
    root = Path(__file__).resolve().parents[1]
    with psycopg.connect(dsn, autocommit=True) as admin:
        # Role is cluster-wide: insist on an isolated cluster without an existing role.
        assert not admin.execute("SELECT 1 FROM pg_roles WHERE rolname='omneum_ingestion'").fetchone()
        admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name)))
        test_dsn = make_conninfo(dsn, dbname=name)
        try:
            with psycopg.connect(test_dsn, autocommit=True) as db:
                db.execute((root / "migrations/production_001.sql").read_text())
                db.execute((root / "migrations/production_002_ingestion.sql").read_text())
                db.execute((root / "migrations/production_003_observation_subtypes.sql").read_text())
                db.execute((root / "migrations/production_004_assertion_subtype_integrity.sql").read_text())
                db.execute((root / "migrations/production_005_contribution_reports.sql").read_text())
            yield test_dsn
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
            admin.execute("DROP ROLE IF EXISTS omneum_ingestion")


@pytest.fixture
def bound(database):
    import psycopg
    with psycopg.connect(database, autocommit=True) as db:
        db.execute("TRUNCATE control.ingestion_receipts, network.evaluation_runs, network.sources, network.claims, control.ingestion_principals, control.workspaces, control.organizations, control.installations CASCADE")
        org = db.execute("INSERT INTO control.organizations DEFAULT VALUES RETURNING id").fetchone()[0]
        workspace = db.execute("INSERT INTO control.workspaces(organization_id) VALUES (%s) RETURNING id", (org,)).fetchone()[0]
        installation = db.execute("INSERT INTO control.installations DEFAULT VALUES RETURNING id").fetchone()[0]
        db.execute("INSERT INTO control.ingestion_principals VALUES (%s,%s,%s,true)", (PRINCIPAL, installation, workspace))
        db.execute("INSERT INTO control.consent_grants(installation_id,scope,consent_version) VALUES (%s,'research_context_graph','1')", (installation,))
        @contextmanager
        def connection():
            with psycopg.connect(database, autocommit=True) as conn:
                conn.execute("SET ROLE omneum_ingestion")
                yield conn
        yield db, service(connection), connection, installation, workspace


def counts(db):
    assert db.execute('SELECT count(*) FROM network.assertion_observations').fetchone() == db.execute(
        'SELECT count(*) FROM network.observations').fetchone()
    return db.execute("""SELECT
        (SELECT count(*) FROM control.ingestion_receipts),
        (SELECT count(*) FROM network.evaluation_runs),
        (SELECT count(*) FROM network.observations),
        (SELECT count(*) FROM network.sources),
        (SELECT count(*) FROM network.claims),
        (SELECT count(*) FROM network.source_scores),
        (SELECT count(*) FROM network.claim_scores),
        (SELECT count(*) FROM network.source_dependencies)""").fetchone()


def test_persist_and_retry(bound):
    db, handler, _, installation, workspace = bound
    first = submit(handler)
    assert first.status == 200
    assert submit(handler) == first
    assert counts(db) == (1, 1, 2, 2, 1, 1, 1, 1)
    row = db.execute("""SELECT r.installation_id, p.workspace_id FROM network.evaluation_runs r
                        JOIN control.ingestion_principals p USING(installation_id) WHERE r.id=%s""", (first.evaluation_run_id,)).fetchone()
    assert row == (installation, workspace)
    assert db.execute("SELECT count(*) FROM public.observations").fetchone()[0] == 0
    assert db.execute("SELECT bool_and(source_low_id < source_high_id) FROM network.source_dependencies").fetchone()[0]
    p = payload()
    p["evaluator_version"] = "other"
    assert submit(handler, p).status == 409
    assert counts(db) == (1, 1, 2, 2, 1, 1, 1, 1)


def test_concurrent_retry(bound):
    db, handler, *_ = bound
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: submit(handler), range(6)))
    assert all(r.status == 200 for r in results)
    assert len(set(results)) == 1
    assert counts(db) == (1, 1, 2, 2, 1, 1, 1, 1)


def test_concurrent_conflict(bound):
    db, handler, *_ = bound
    def write(i):
        p = payload()
        p["evaluator_version"] = f"v{i}"
        return submit(handler, p)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(write, range(4)))
    assert sorted(r.status for r in results) == [200, 409, 409, 409]
    assert counts(db) == (1, 1, 2, 2, 1, 1, 1, 1)


def test_rollback(bound, monkeypatch):
    from omneum.ingestion import postgres
    db, handler, *_ = bound
    original = postgres._write_run
    def fail(*args):
        original(*args)
        raise RuntimeError("private SQL credential linkage token")
    monkeypatch.setattr(postgres, "_write_run", fail)
    response = submit(handler)
    assert response.status == 503
    assert "private" not in repr(response)
    assert counts(db) == (0,) * 8
    monkeypatch.setattr(postgres, "_write_run", original)
    assert submit(handler).status == 200


def test_missing_disabled_and_revoked_authorization(bound):
    db, handler, *_ = bound
    db.execute("UPDATE control.ingestion_principals SET enabled=false")
    assert submit(handler).status == 403
    db.execute("UPDATE control.ingestion_principals SET enabled=true")
    db.execute("UPDATE control.consent_grants SET revoked_at=now()")
    assert submit(handler).status == 403
    db.execute("DELETE FROM control.ingestion_principals")
    assert submit(handler).status == 403
    assert counts(db) == (0,) * 8


def test_workspace_isolation(bound):
    db, first, connection, *_ = bound
    other = uuid4()
    org = db.execute("INSERT INTO control.organizations DEFAULT VALUES RETURNING id").fetchone()[0]
    workspace = db.execute("INSERT INTO control.workspaces(organization_id) VALUES (%s) RETURNING id", (org,)).fetchone()[0]
    installation = db.execute("INSERT INTO control.installations DEFAULT VALUES RETURNING id").fetchone()[0]
    db.execute("INSERT INTO control.ingestion_principals VALUES (%s,%s,%s,true)", (other, installation, workspace))
    db.execute("INSERT INTO control.consent_grants(installation_id,scope,consent_version) VALUES (%s,'research_context_graph','1')", (installation,))
    class OtherAuth:
        def authenticate(self, credential):
            return other if credential == "other-key" else None
    second = service(connection, OtherAuth())
    a = submit(first)
    b = submit(second, authorization="Bearer other-key")
    assert a.status == b.status == 200
    assert a.receipt_id != b.receipt_id and a.evaluation_run_id != b.evaluation_run_id
    assert submit(second, authorization="Bearer other-key") == b
    p = payload()
    p["workspace_id"] = str(workspace)
    assert submit(first, p).status == 400
    assert counts(db) == (2, 2, 4, 2, 1, 2, 2, 2)  # Network identities are intentionally global.


def test_least_privilege(bound):
    import psycopg
    _, _, connection, *_ = bound
    with connection() as conn:
        for statement in (
            "CREATE TABLE network.evil (id int)",
            "INSERT INTO public.sources(source_kind,identifier) VALUES ('url','secret')",
            "UPDATE control.ingestion_principals SET enabled=true",
            "DELETE FROM control.ingestion_receipts",
            "ALTER TABLE network.sources ADD COLUMN raw text",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(statement)


def test_existing_transaction_rejected(bound):
    _, _, factory, *_ = bound
    @contextmanager
    def in_transaction():
        with factory() as conn, conn.transaction():
            yield conn
    assert submit(service(in_transaction)).status == 503


def test_no_logging(bound, caplog):
    _, handler, *_ = bound
    assert submit(handler).status == 200
    assert not caplog.records


@pytest.mark.parametrize("result", [True, "principal", {"workspace_id": str(uuid4())}])
def test_authenticator_invalid_return(result):
    class Invalid:
        def authenticate(self, credential):
            return result
    assert submit(service(auth=Invalid())).status == 401


def test_mixed_versions():
    p = payload()
    p["claims"][0]["key_version"] = 2
    handler = IngestionService(authenticator=Auth(), connection_factory=forbidden_connection,
                               allowed_key_versions=frozenset({1, 2}))
    assert submit(handler, p).status == 400


def test_json_key_order_does_not_change_retry(bound):
    _, handler, *_ = bound
    first = submit(handler)
    response = handler.handle(authorization="Bearer test-key",
                              body=json.dumps(payload(), sort_keys=True, indent=2).encode())
    assert response == first


def test_failure_after_receipt_insert_rolls_back(bound):
    db, handler, *_ = bound
    db.execute("""CREATE FUNCTION control.test_fail_receipt() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'private SQL details'; END; $$""")
    db.execute("""CREATE TRIGGER test_fail AFTER INSERT ON control.ingestion_receipts
                  FOR EACH ROW EXECUTE FUNCTION control.test_fail_receipt()""")
    try:
        assert submit(handler).status == 503
        assert counts(db) == (0,) * 8
    finally:
        db.execute("DROP TRIGGER test_fail ON control.ingestion_receipts")
        db.execute("DROP FUNCTION control.test_fail_receipt()")
    assert submit(handler).status == 200


def test_retry_requires_current_authorization(bound):
    db, handler, *_ = bound
    assert submit(handler).status == 200
    db.execute("UPDATE control.consent_grants SET revoked_at=now()")
    assert submit(handler).status == 403
    assert counts(db) == (1, 1, 2, 2, 1, 1, 1, 1)


def test_binding_cannot_be_reassigned(bound):
    import psycopg
    db, handler, _, _, workspace = bound
    assert submit(handler).status == 200
    other = db.execute("INSERT INTO control.workspaces(organization_id) SELECT organization_id FROM control.workspaces WHERE id=%s RETURNING id", (workspace,)).fetchone()[0]
    with pytest.raises(psycopg.errors.RaiseException):
        db.execute("UPDATE control.ingestion_principals SET workspace_id=%s", (other,))
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        db.execute("DELETE FROM control.ingestion_principals")


def test_owner_connection_rejected(bound, database):
    import psycopg
    db, *_ = bound
    @contextmanager
    def elevated():
        with psycopg.connect(database, autocommit=True) as conn:
            yield conn
    assert submit(service(elevated)).status == 503
    assert counts(db) == (0,) * 8


def test_source_kind_is_a_report_not_a_first_writer_veto(bound):
    db, handler, *_ = bound
    assert submit(handler).status == 200
    p = payload()
    p["idempotency_key"] = "other"
    p["sources"][0]["source_kind"] = "web_document"
    assert submit(handler, p).status == 200
    assert counts(db) == (2, 2, 4, 2, 1, 2, 2, 2)


def test_reported_structural_fields_validated_and_not_published(bound):
    db, handler, *_ = bound
    p = payload()
    p["observations"][0]["observed_bucket"] = "2026-01-01T00:00:00Z"
    p["dependencies"][0].update(retrieval_signal=0.4, signal_components={"retrieval": 0.4},
                                 source_low_cites_source_high=True,
                                 qualifying_time_deltas_seconds=[1.0])
    assert submit(handler, p).status == 200
    p["dependencies"][0]["retrieval_signal"] = 0.5
    assert submit(handler, p).status == 409
    assert db.execute("SELECT count(*) FROM public.sources").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM public.claims").fetchone()[0] == 0


def test_assertion_subtype_failure_is_atomic(bound):
    db, handler, *_ = bound
    db.execute("""CREATE FUNCTION network.test_fail_assertion() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'subtype failure'; END; $$""")
    db.execute("""CREATE TRIGGER test_fail_assertion BEFORE INSERT ON network.assertion_observations
                  FOR EACH ROW EXECUTE FUNCTION network.test_fail_assertion()""")
    try:
        assert submit(handler).status == 503
        assert counts(db) == (0,) * 8
    finally:
        db.execute('DROP TRIGGER test_fail_assertion ON network.assertion_observations')
        db.execute('DROP FUNCTION network.test_fail_assertion()')
    assert submit(handler).status == 200
    assert db.execute("SELECT count(*) FROM network.assertion_observation_envelopes").fetchone() == (2,)


def test_direct_sql_network_assertion_commit_integrity(bound):
    import psycopg
    db, handler, *_ = bound
    assert submit(handler).status == 200
    run, source, claim = db.execute('''SELECT o.evaluation_run_id,o.source_id,a.claim_id
        FROM network.observations o JOIN network.assertion_observations a ON a.observation_id=o.id LIMIT 1''').fetchone()
    with pytest.raises(psycopg.errors.CheckViolation, match='requires an assertion subtype'):
        db.execute('INSERT INTO network.observations(evaluation_run_id,source_id) VALUES (%s,%s)', (run,source))
    with db.transaction():
        oid = db.execute('INSERT INTO network.observations(evaluation_run_id,source_id) VALUES (%s,%s) RETURNING id', (run,source)).fetchone()[0]
        db.execute('INSERT INTO network.assertion_observations VALUES (%s,%s)', (oid,claim))
    future = db.execute("INSERT INTO network.observations(evaluation_run_id,source_id,observation_type) VALUES (%s,%s,'measurement') RETURNING id", (run,source)).fetchone()[0]
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        db.execute('INSERT INTO network.assertion_observations VALUES (%s,%s)', (future,claim))
    assert db.execute('SELECT claim_id FROM network.assertion_observation_envelopes WHERE id=%s', (oid,)).fetchone() == (claim,)
    with pytest.raises(psycopg.errors.CheckViolation, match='truncate'):
        db.execute('TRUNCATE network.assertion_observations')


def test_direct_sql_published_assertion_commit_integrity(bound):
    import psycopg
    db, *_ = bound
    source = db.execute("INSERT INTO public.sources(source_kind,identifier) VALUES ('web_document','https://example.com/published') RETURNING id").fetchone()[0]
    claim = db.execute("INSERT INTO public.claims(entity_namespace,entity,attribute,value) VALUES ('service','entity','status','\"ok\"') RETURNING id").fetchone()[0]
    with pytest.raises(psycopg.errors.CheckViolation, match='requires an assertion subtype'):
        db.execute('INSERT INTO public.observations(source_id) VALUES (%s)', (source,))
    with db.transaction():
        oid = db.execute('INSERT INTO public.observations(source_id) VALUES (%s) RETURNING id', (source,)).fetchone()[0]
        db.execute('INSERT INTO public.assertion_observations VALUES (%s,%s)', (oid,claim))
    future = db.execute("INSERT INTO public.observations(source_id,observation_type) VALUES (%s,'event') RETURNING id", (source,)).fetchone()[0]
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        db.execute('INSERT INTO public.assertion_observations VALUES (%s,%s)', (future,claim))
    assert db.execute('SELECT claim_id FROM public.assertion_observation_envelopes WHERE id=%s', (oid,)).fetchone() == (claim,)


@pytest.mark.parametrize('component', ['private-source-identifier', 'credential', 'metadata'])
def test_unapproved_component_names_rejected(component):
    p = payload()
    p['dependencies'][0]['signal_components'] = {component: 0.5}
    assert submit(service(), p).status == 400


@pytest.mark.parametrize('revoke', [
    'UPDATE control.ingestion_principals SET enabled=false',
    'UPDATE control.consent_grants SET revoked_at=now()',
])
def test_revocation_while_waiting_for_installation_lock(bound, revoke):
    import time
    db, handler, _, installation, _ = bound
    lock = int.from_bytes(installation.bytes[:8], 'big', signed=True)
    db.execute('SELECT pg_advisory_lock(%s)', (lock,))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(submit, handler)
        try:
            deadline = time.monotonic() + 3
            while not db.execute("""SELECT EXISTS (SELECT 1 FROM pg_locks
                    WHERE locktype='advisory' AND NOT granted
                    AND classid=%s AND objid=%s)""",
                    ((lock >> 32) & 0xffffffff, lock & 0xffffffff)).fetchone()[0]:
                assert time.monotonic() < deadline, 'ingestion did not wait on lock'
                time.sleep(0.01)
            db.execute(revoke)
        finally:
            db.execute('SELECT pg_advisory_unlock(%s)', (lock,))
        assert future.result(timeout=5).status == 403
    assert counts(db) == (0,) * 8


def test_authenticated_unissued_tokens_are_not_attested(bound):
    db, handler, *_ = bound
    p = payload()
    # No VOPRF server is contacted. Arbitrary canonical bytes are sufficient.
    source_token, claim_token = os.urandom(64), os.urandom(64)
    p['sources'][0]['source_token'] = encode_unpadded(source_token, expected_length=64)
    p['claims'][0]['claim_token'] = encode_unpadded(claim_token, expected_length=64)
    assert submit(handler, p).status == 200
    assert db.execute('SELECT count(*) FROM network.sources WHERE source_token=%s',
                      (source_token,)).fetchone()[0] == 1
    assert db.execute('SELECT count(*) FROM network.claims WHERE claim_token=%s',
                      (claim_token,)).fetchone()[0] == 1


def test_client_scores_are_stored_without_attestation_or_recomputation(bound):
    db, handler, *_ = bound
    p = payload()
    p['source_scores'][0]['reliability'] = 0.12345
    p['claim_scores'][0]['support'] = 0.54321
    p['dependencies'][0]['dependency_score'] = 0.98765
    response = submit(handler, p)
    assert response.status == 200
    for table, column, expected in (
        ('source_scores', 'reliability_score', 0.12345),
        ('claim_scores', 'support_score', 0.54321),
        ('source_dependencies', 'dependency_score', 0.98765),
    ):
        # Identifiers are fixed test constants, never request values.
        assert db.execute(f'SELECT {column} FROM network.{table} WHERE evaluation_run_id=%s',
                          (response.evaluation_run_id,)).fetchone()[0] == expected
