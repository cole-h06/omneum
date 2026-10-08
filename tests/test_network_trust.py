"""Contributions remain attributed reports, with bounded storage influence."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from omneum.base64url import encode_unpadded
from omneum.ingestion import IngestionLimits, IngestionService
from test_ingestion import (Auth, PRINCIPAL, bound, database, counts, payload, submit)


def limited(bound, **limits):
    return IngestionService(authenticator=Auth(), connection_factory=bound[2],
        allowed_key_versions=frozenset({1}), limits=replace(IngestionLimits(), **limits))


def memberships(db):
    return db.execute('SELECT (SELECT count(*) FROM network.reported_sources), '
                      '(SELECT count(*) FROM network.reported_claims)').fetchone()


def contributors(db):
    # This counts authenticated reporters, not reported sources or client scores.
    return db.execute('''SELECT count(DISTINCT r.installation_id)
        FROM network.observations o
        JOIN network.assertion_observations a ON a.observation_id=o.id
        JOIN network.evaluation_runs r ON r.id=o.evaluation_run_id
        JOIN network.claims c ON c.id=a.claim_id WHERE c.claim_token=%s''',
        (bytes([3]) * 64,)).fetchone()[0]


def other_contributor(bound):
    db, _, factory, *_ = bound
    principal, installation = uuid4(), uuid4()
    workspace = db.execute('SELECT id FROM control.workspaces LIMIT 1').fetchone()[0]
    db.execute('INSERT INTO control.installations(id) VALUES (%s)', (installation,))
    db.execute('INSERT INTO control.ingestion_principals VALUES (%s,%s,%s,true)',
               (principal, installation, workspace))
    db.execute("INSERT INTO control.consent_grants(installation_id,scope,consent_version) "
               "VALUES (%s,'research_context_graph','1')", (installation,))
    class OtherAuth:
        def authenticate(self, credential):
            return principal if credential == 'test-key' else None
    return IngestionService(authenticator=OtherAuth(), connection_factory=factory,
                            allowed_key_versions=frozenset({1})), installation


def test_replay_and_repeated_reports_are_one_contributor(bound):
    db, handler, _, installation, _ = bound
    first = submit(handler)
    for _ in range(5):
        assert submit(handler) == first
    assert counts(db)[1] == 1
    p = payload()
    p['idempotency_key'] = 'another-report'
    assert submit(handler, p).status == 200
    assert counts(db)[1:3] == (2, 4)
    assert contributors(db) == 1
    assert db.execute('''SELECT DISTINCT p.principal_id,r.installation_id
        FROM network.reported_sources s JOIN network.evaluation_runs r ON r.id=s.evaluation_run_id
        JOIN control.ingestion_principals p ON p.installation_id=r.installation_id''').fetchall() == [(PRINCIPAL, installation)]


def test_two_authenticated_reporters_remain_distinct(bound):
    db, first, *_ = bound
    second, _ = other_contributor(bound)
    assert submit(first).status == submit(second).status == 200
    assert contributors(db) == 2
    assert counts(db)[3:5] == (2, 1)  # Shared identities, separate reports.
    assert memberships(db) == (4, 2)


def test_unused_identity_attribution_is_retained(bound):
    db, handler, _, installation, _ = bound
    p = payload()
    p['observations'] = p['source_scores'] = p['claim_scores'] = p['dependencies'] = []
    result = submit(handler, p)
    assert result.status == 200
    assert memberships(db) == (2, 1)
    assert db.execute('''SELECT DISTINCT r.installation_id FROM network.reported_claims c
        JOIN network.evaluation_runs r ON r.id=c.evaluation_run_id''').fetchall() == [(installation,)]


def test_fabricated_sources_do_not_make_authenticated_consensus(bound, monkeypatch):
    db, handler, *_ = bound
    monkeypatch.setattr('omneum.inference.infer', lambda *a: pytest.fail('Network intake ran BRAID'))
    p = payload()
    n = 30
    p['sources'] = [dict(source_id=f's{i:03d}', source_token=encode_unpadded(os.urandom(64), expected_length=64),
        source_kind='url', key_version=1) for i in range(n)]
    p['observations'] = [dict(source_id=s['source_id'], claim_id='c1') for s in p['sources']]
    p['source_scores'] = []
    p['dependencies'] = []
    p['claim_scores'][0].update(supporting_source_count=n, estimated_independent_support_count=float(n), support=999.0)
    response = submit(handler, p)
    assert response.status == 200
    assert contributors(db) == 1
    assert db.execute('SELECT estimated_independent_support_count FROM network.claim_scores').fetchone()[0] == n
    # A reported independence estimate is not a server-derived contributor count.
    assert set(asdict(response)) == {'status', 'code', 'receipt_id', 'evaluation_run_id'}
    assert db.execute('SELECT count(*) FROM public.observations').fetchone()[0] == 0


def test_copied_tokens_do_not_override_or_veto_other_reports(bound):
    db, first, *_ = bound
    second, _ = other_contributor(bound)
    p = payload()
    # First reporter may lie about the kind of an otherwise correctly formed token.
    p['sources'][0]['source_kind'] = 'web_document'
    a = submit(first, p)
    original = db.execute('''SELECT source_id,source_kind FROM network.reported_sources
        WHERE evaluation_run_id=%s ORDER BY source_id''', (a.evaluation_run_id,)).fetchall()
    b = submit(second)  # Same tokens; different reported kind and scores.
    assert a.status == b.status == 200
    assert db.execute('''SELECT source_id,source_kind FROM network.reported_sources
        WHERE evaluation_run_id=%s ORDER BY source_id''', (a.evaluation_run_id,)).fetchall() == original
    assert db.execute('''SELECT count(*) FROM network.reported_sources
        WHERE evaluation_run_id=%s AND source_kind='url' ''', (b.evaluation_run_id,)).fetchone()[0] == 2
    assert contributors(db) == 2
    with bound[2]() as conn:
        import psycopg
        for table in ('reported_sources', 'reported_claims', 'source_scores', 'claim_scores', 'source_dependencies'):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(f'DELETE FROM network.{table}')


@pytest.mark.parametrize('limit,value', [('contributions', 1), ('sources', 3), ('claims', 1),
                                       ('observations', 3), ('dependencies', 1)])
def test_daily_growth_budgets_are_atomic_and_replays_free(bound, limit, value):
    db, *_ = bound
    handler = limited(bound, **{limit: value})
    accepted = submit(handler)
    assert accepted.status == 200
    before = counts(db), memberships(db)
    p = payload()
    p['idempotency_key'] = 'new-report'
    response = submit(handler, p)
    assert (response.status, response.code) == (429, 'contribution_quota_exceeded')
    assert (counts(db), memberships(db)) == before
    assert submit(handler) == accepted


def test_concurrent_growth_cannot_bypass_budget(bound):
    db, *_ = bound
    handler = limited(bound, contributions=2)
    def write(i):
        p = payload()
        p['idempotency_key'] = f'unique-{i}'
        return submit(handler, p)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(write, range(6)))
    assert sorted(r.status for r in results) == [200, 200, 429, 429, 429, 429]
    assert counts(db)[1] == 2
    assert memberships(db) == (4, 2)


def test_budgets_are_per_authenticated_installation(bound):
    first = limited(bound, contributions=1)
    assert submit(first).status == 200
    second, _ = other_contributor(bound)
    second._limits = IngestionLimits(contributions=1)
    assert submit(second).status == 200
    p = payload()
    p['idempotency_key'] = 'new-report'
    assert submit(first, p).status == submit(second, p).status == 429


def test_failed_ingestion_does_not_consume_budget(bound, monkeypatch):
    from omneum.ingestion import postgres
    db, *_ = bound
    handler = limited(bound, contributions=1)
    original = postgres._write_run
    def fail(*args):
        original(*args)
        raise RuntimeError('failed after writes')
    monkeypatch.setattr(postgres, '_write_run', fail)
    assert submit(handler).status == 503
    assert counts(db) == (0,) * 8
    assert memberships(db) == (0, 0)
    monkeypatch.setattr(postgres, '_write_run', original)
    assert submit(handler).status == 200


def test_previous_utc_day_does_not_consume_today_budget(bound):
    db, *_ = bound
    handler = limited(bound, contributions=1)
    assert submit(handler).status == 200
    db.execute("UPDATE network.evaluation_runs SET created_at="
               "(date_trunc('day', now() AT TIME ZONE 'UTC') - interval '1 second') AT TIME ZONE 'UTC'")
    p = payload()
    p['idempotency_key'] = 'today-report'
    assert submit(handler, p).status == 200


def test_malformed_and_oversized_reports_leave_membership_unchanged(bound):
    db, handler, *_ = bound
    p = payload()
    p['observations'][0]['claim_id'] = 'missing'
    assert submit(handler, p).status == 400
    assert handler.handle(authorization='Bearer test-key', body=b'x' * 1_048_577).status == 413
    assert counts(db) == (0,) * 8
    assert memberships(db) == (0, 0)


@pytest.mark.parametrize('value', [0, -1, True, float('inf'), 2**31])
def test_invalid_server_budgets(value):
    with pytest.raises(ValueError):
        IngestionLimits(contributions=value)


def test_report_membership_and_budget_migrate_legacy_rows(bound):
    db, handler, *_ = bound
    assert submit(handler).status == 200
    before = counts(db)
    db.execute('DROP TABLE network.reported_sources, network.reported_claims CASCADE')
    db.execute('ALTER TABLE network.evaluation_runs DROP COLUMN dependency_count')
    db.execute('ALTER TABLE network.source_dependencies DROP COLUMN reported_evidence')
    migration = Path(__file__).resolve().parents[1] / 'migrations/production_005_contribution_reports.sql'
    db.execute(migration.read_text())
    assert counts(db) == before
    assert memberships(db) == (2, 1)
    assert db.execute('SELECT dependency_count FROM network.evaluation_runs').fetchone()[0] == 1
    p = payload()
    p['idempotency_key'] = 'after-migration'
    assert submit(handler, p).status == 200


def test_reported_dependency_evidence_is_preserved_with_uuid_direction(bound):
    from uuid import UUID
    db, handler, *_ = bound
    for n, identity in ((1, UUID(int=2)), (2, UUID(int=1))):
        db.execute('INSERT INTO network.sources(id,source_token,source_kind,key_version) '
                   "VALUES (%s,%s,'url','1')", (identity, bytes([n]) * 64))
    p = payload()
    p['dependencies'][0].update(retrieval_signal=0.4, signal_components={'retrieval': 0.4},
        source_low_upstream_of_source_high=True, source_high_cites_source_low=True,
        source_low_parent_count=2, source_high_parent_count=3, same_owner=True,
        matching_claim_count=1, qualifying_time_deltas_seconds=[1.0])
    assert submit(handler, p).status == 200
    low, high, retrieval, evidence = db.execute('''SELECT source_low_id,source_high_id,
        retrieval_signal,reported_evidence FROM network.source_dependencies''').fetchone()
    assert (low, high) == (UUID(int=1), UUID(int=2))
    assert retrieval == 0.4
    assert evidence == dict(signal_components={'retrieval': 0.4},
        source_low_upstream_of_source_high=False, source_high_upstream_of_source_low=True,
        source_low_cites_source_high=True, source_high_cites_source_low=False,
        source_low_parent_count=3, source_high_parent_count=2, same_owner=True,
        matching_claim_count=1, qualifying_time_deltas_seconds=[1.0])


def test_per_run_membership_foreign_keys_reject_cross_report_structure(bound):
    import psycopg
    db, handler, *_ = bound
    response = submit(handler)
    p = payload()
    p['idempotency_key'] = 'unrelated-claim'
    p['claims'][0]['claim_token'] = encode_unpadded(bytes([99]) * 64, expected_length=64)
    other = submit(handler, p)
    assert other.status == 200
    original_observation = db.execute('SELECT id FROM network.observations WHERE evaluation_run_id=%s LIMIT 1',
                                     (response.evaluation_run_id,)).fetchone()[0]
    source = db.execute('SELECT source_id FROM network.observations WHERE id=%s', (original_observation,)).fetchone()[0]
    claim = db.execute('SELECT id FROM network.claims WHERE claim_token=%s', (bytes([99]) * 64,)).fetchone()[0]
    with pytest.raises(psycopg.errors.ForeignKeyViolation), db.transaction():
        oid = db.execute('INSERT INTO network.observations(evaluation_run_id,source_id) VALUES (%s,%s) RETURNING id',
                         (response.evaluation_run_id, source)).fetchone()[0]
        db.execute('INSERT INTO network.assertion_observations VALUES (%s,%s)', (oid, claim))
    assert counts(db)[2] == 4
