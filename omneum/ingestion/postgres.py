"""Persist attributed contributor reports, never authoritative Network scores.

Structural validation does not establish truth, independence or VOPRF issuance.
All SQL identifiers are fixed server constants.
"""

from uuid import uuid4

from omneum.base64url import decode_unpadded
from .limits import IngestionLimits


class Rejected(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(code)


def persist(connection, principal, contribution, fingerprint, limits=IngestionLimits()):
    from psycopg.pq import TransactionStatus
    from psycopg.rows import tuple_row

    if connection.info.transaction_status != TransactionStatus.IDLE:
        raise RuntimeError("ingestion requires an idle exclusive connection")
    c = contribution
    with connection.transaction():
        with connection.cursor(row_factory=tuple_row) as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
            cur.execute("SELECT current_user = 'omneum_ingestion'")
            if not cur.fetchone()[0]:
                raise RuntimeError("dedicated ingestion role required")
            cur.execute("SET LOCAL statement_timeout = '10s'")
            cur.execute("SET LOCAL lock_timeout = '5s'")
            cur.execute("""
                SELECT p.installation_id, p.workspace_id, w.organization_id
                FROM control.ingestion_principals p
                JOIN control.workspaces w ON w.id = p.workspace_id
                WHERE p.principal_id = %s AND p.enabled
                  AND EXISTS (SELECT 1 FROM control.consent_grants g
                    WHERE g.installation_id = p.installation_id
                    AND g.scope = 'research_context_graph' AND g.revoked_at IS NULL)
            """, (principal,))
            binding = cur.fetchone()
            if binding is None:
                raise Rejected(403, "forbidden")
            installation, _workspace, _organization = binding
            # Transaction-scoped lock serializes requests for this installation.
            # It precedes the receipt lookup and all writes. Collisions only serialize.
            cur.execute("SELECT pg_advisory_xact_lock(%s)",
                        (int.from_bytes(installation.bytes[:8], 'big', signed=True),))
            # Authorization may have been revoked while this request waited.
            # READ COMMITTED gives this check a fresh snapshot before replay/write.
            cur.execute("""
                SELECT p.installation_id, p.workspace_id, w.organization_id
                FROM control.ingestion_principals p
                JOIN control.workspaces w ON w.id = p.workspace_id
                WHERE p.principal_id = %s AND p.enabled
                  AND EXISTS (SELECT 1 FROM control.consent_grants g
                    WHERE g.installation_id = p.installation_id
                    AND g.scope = 'research_context_graph' AND g.revoked_at IS NULL)
            """, (principal,))
            if cur.fetchone() != binding:
                raise Rejected(403, "forbidden")
            cur.execute("""
                SELECT id, payload_sha256, evaluation_run_id, accepted_at
                FROM control.ingestion_receipts
                WHERE installation_id = %s AND idempotency_key = %s
            """, (installation, c.idempotency_key))
            existing = cur.fetchone()
            if existing:
                if existing[1] != fingerprint or existing[2] is None or existing[3] is None:
                    raise Rejected(409, "idempotency_conflict")
                return existing[0], existing[2]
            _check_budget(cur, installation, c, limits)
            run = _write_run(cur, installation, c)
            receipt = uuid4()
            cur.execute("""
                INSERT INTO control.ingestion_receipts
                    (id, installation_id, idempotency_key, payload_sha256,
                     evaluation_run_id, accepted_at)
                VALUES (%s, %s, %s, %s, %s, now())
            """, (receipt, installation, c.idempotency_key, fingerprint, run))
    return receipt, run


def _check_budget(cur, installation, c, limits):
    # Same installation lock as idempotency. Committed run rows are the ledger,
    # so retries and rolled-back writes consume no quota. Use transaction time
    # to match created_at's now(), including requests spanning UTC midnight.
    cur.execute("""
        SELECT count(*), COALESCE(sum(source_count), 0),
               COALESCE(sum(claim_count), 0), COALESCE(sum(observation_count), 0),
               COALESCE(sum(dependency_count), 0)
        FROM network.evaluation_runs
        WHERE installation_id=%s
          AND created_at >= date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'
          AND created_at < (date_trunc('day', now() AT TIME ZONE 'UTC')
                           + interval '1 day') AT TIME ZONE 'UTC'
    """, (installation,))
    used = cur.fetchone()
    incoming = (1, len(c.sources), len(c.claims), len(c.observations), len(c.dependencies))
    if any(previous + additional > maximum
           for previous, additional, maximum in zip(used, incoming, limits.values(), strict=True)):
        raise Rejected(429, "contribution_quota_exceeded")


def _write_run(cur, installation, c):
    from psycopg.types.json import Jsonb

    sources, claims = {}, {}
    # Stable token order prevents deadlocks when installations share identities.
    for s in sorted(c.sources, key=lambda s: (s.key_version, s.source_token)):
        cur.execute("""
            INSERT INTO network.sources (source_token, source_kind, key_version)
            VALUES (%s, %s, %s)
            ON CONFLICT (source_token, key_version) DO UPDATE SET last_seen_at = now()
            RETURNING id
        """, (decode_unpadded(s.source_token, expected_length=64), s.source_kind, str(s.key_version)))
        row = cur.fetchone()
        if row is None:
            raise Rejected(400, "invalid_contribution")
        sources[s.source_id] = row[0]
    for s in sorted(c.claims, key=lambda s: (s.key_version, s.claim_token)):
        cur.execute("""
            INSERT INTO network.claims (claim_token, key_version) VALUES (%s, %s)
            ON CONFLICT (claim_token, key_version) DO UPDATE SET last_seen_at = now()
            RETURNING id
        """, (decode_unpadded(s.claim_token, expected_length=64), str(s.key_version)))
        claims[s.claim_id] = cur.fetchone()[0]
    cur.execute("""
        INSERT INTO network.evaluation_runs
            (installation_id, evaluator_version, estimator_version, status,
             source_count, claim_count, observation_count, dependency_count)
        VALUES (%s, %s, %s, 'completed', %s, %s, %s, %s) RETURNING id
    """, (installation, c.evaluator_version, c.estimator_version,
          len(sources), len(claims), len(c.observations), len(c.dependencies)))
    run = cur.fetchone()[0]
    # Record every submitted identity, even when it has no observation/score.
    # These memberships and classifications are reports, never global truth.
    for source in c.sources:
        cur.execute("""INSERT INTO network.reported_sources
            (evaluation_run_id, source_id, source_kind) VALUES (%s, %s, %s)""",
            (run, sources[source.source_id], source.source_kind))
    for claim in c.claims:
        cur.execute("""INSERT INTO network.reported_claims
            (evaluation_run_id, claim_id) VALUES (%s, %s)""", (run, claims[claim.claim_id]))
    for o in c.observations:
        cur.execute("""
            INSERT INTO network.observations
                (evaluation_run_id, source_id, observation_type, observed_bucket)
            VALUES (%s, %s, %s, %s) RETURNING id
        """, (run, sources[o.source_id], o.observation_type, o.observed_bucket))
        observation_id = cur.fetchone()[0]
        cur.execute("""
            INSERT INTO network.assertion_observations (observation_id, claim_id)
            VALUES (%s, %s)
        """, (observation_id, claims[o.claim_id]))
    for s in c.source_scores:
        cur.execute("""
            INSERT INTO network.source_scores
                (evaluation_run_id, source_id, reliability_score, contribution_score)
            VALUES (%s, %s, %s, %s)
        """, (run, sources[s.source_id], s.reliability, s.contribution_score))
    for s in c.claim_scores:
        cur.execute("""
            INSERT INTO network.claim_scores
                (evaluation_run_id, claim_id, support_score, supporting_source_count,
                 estimated_independent_support_count, dependency_cluster_count,
                 dependency_signal_coverage)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (run, claims[s.claim_id], s.support, s.supporting_source_count,
              s.estimated_independent_support_count, s.dependency_cluster_count,
              s.dependency_signal_coverage))
    for d in c.dependencies:
        low, high = sorted((sources[d.source_low_id], sources[d.source_high_id]))
        # Wire aliases and UUIDs may sort differently. Preserve reported
        # direction against the stored UUID endpoints, not the caller aliases.
        ordered = sources[d.source_low_id] == low
        a, b = ("low", "high") if ordered else ("high", "low")
        evidence = {
            "signal_components": d.signal_components,
            "source_low_upstream_of_source_high": getattr(d, f"source_{a}_upstream_of_source_{b}"),
            "source_high_upstream_of_source_low": getattr(d, f"source_{b}_upstream_of_source_{a}"),
            "source_low_cites_source_high": getattr(d, f"source_{a}_cites_source_{b}"),
            "source_high_cites_source_low": getattr(d, f"source_{b}_cites_source_{a}"),
            "source_low_parent_count": getattr(d, f"source_{a}_parent_count"),
            "source_high_parent_count": getattr(d, f"source_{b}_parent_count"),
            "same_owner": d.same_owner,
            "matching_claim_count": d.matching_claim_count,
            "qualifying_time_deltas_seconds": d.qualifying_time_deltas_seconds,
        }
        cur.execute("""
            INSERT INTO network.source_dependencies
                (evaluation_run_id, source_low_id, source_high_id, dependency_score,
                 upstream_signal, citation_signal, assertion_lineage_signal, ownership_signal,
                 temporal_signal, graph_signal, signal_coverage, estimator_version,
                 retrieval_signal, reported_evidence)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (run, low, high, d.dependency_score, d.upstream_signal, d.citation_signal,
              d.assertion_lineage_signal, d.ownership_signal, d.temporal_signal,
              d.graph_signal, d.signal_coverage, c.estimator_version,
              d.retrieval_signal, Jsonb(evidence)))
    return run
