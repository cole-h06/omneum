"""Evaluation history integration tests; use the disposable storage test DSN."""

import asyncio
from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
from uuid import UUID, uuid4

import pytest

from omneum import Claim, Observation, OmneumClient, Source, SourceReference
from omneum.canonicalization import canonicalize_source
from omneum.dependency import DependencyEstimatorConfig
from omneum.storage import PostgresStorage
from omneum.storage import graph
from omneum.tools.evaluate_context import AssertionEvaluationService
from test_client import LocalEvaluator, make_config, make_server
from test_evaluate_context import make_state
from test_storage import db, workspace  # Shared opt-in database fixtures.


@pytest.fixture(scope="module")
def computed(tmp_path_factory):
    """Compute through the public client and obtain real VOPRF linkage tokens."""
    server = make_server(tmp_path_factory.mktemp("evaluation-linkage"))
    service = AssertionEvaluationService(make_state(server=server))

    class Evaluator(LocalEvaluator):
        async def evaluate_context(self, request):
            return await service.evaluate(request)

    client = OmneumClient(make_config(server), Evaluator(server), local_persistence=None)
    estimator = DependencyEstimatorConfig(
        upstream_weight=0.25, citation_weight=0.2, assertion_lineage_weight=0.2,
        ownership_weight=0.1, temporal_weight=0.1, graph_weight=0.15,
        temporal_window_seconds=7200.0, retrieval_weight=0.1,
        dependency_cluster_threshold=0.5,
    )
    a = Source("web_publisher", "https://private-a.example", "private-owner")
    b = Source("web_publisher", "https://private-b.example", "private-owner")
    c1 = Claim("service", "private-entity", "return window", "private-value-1")
    c2 = Claim("service", "private-entity", "shipping time", "private-value-2")
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    observations = (
        Observation("a1", a, c1, now, upstream_sources=(), cited_sources=(),
                    parent_observation_ids=(), retrievals=()),
        Observation("b1", b, c1, now, upstream_sources=(),
                    cited_sources=(SourceReference(a.kind, a.identifier),),
                    parent_observation_ids=("a1",), retrievals=()),
        Observation("b2", b, c2, now, upstream_sources=(), cited_sources=(),
                    parent_observation_ids=(), retrievals=()),
    )

    async def compute():
        evaluation = await client.evaluate_context(observations, estimator=estimator)
        sources = {source: await client.link_source(source.kind, source.identifier)
                   for source in (a, b)}
        claims = {claim: await client.link_claim(claim.entity_namespace, claim.entity,
                                                claim.attribute, claim.value)
                  for claim in (c1, c2)}
        return evaluation, sources, claims

    try:
        evaluation, source_tokens, claim_tokens = asyncio.run(compute())
    finally:
        service.close()
    return evaluation, source_tokens, claim_tokens, estimator, observations


@pytest.fixture
def prepared(db, workspace, computed):
    evaluation, sources, claims, estimator, observations = computed
    # Force reverse UUID order relative to the public pair's canonical source
    # order. The public model itself correctly forbids a reversed source pair.
    source_ids = sorted((uuid4(), uuid4()), reverse=True)
    for source, source_id in zip(sources, source_ids):
        db.execute("""INSERT INTO public.sources(id,workspace_id,source_token)
                      VALUES (%s,%s,%s)""", (source_id, workspace, sources[source].value))
    stored = []
    storage = PostgresStorage(db)
    for observation in observations:
        stored.append(storage.persist_observation(
            workspace_id=workspace, observation=observation,
            source_token=sources[observation.source], claim_token=claims[observation.claim],
        ))
    return dict(workspace_id=workspace, evaluation=evaluation, source_tokens=sources,
                claim_tokens=claims, estimator=estimator), stored


def save(db, prepared):
    with db.transaction():
        return PostgresStorage(db).persist_evaluation(**prepared[0])


def dependencies(db, workspace):
    db.execute("LOAD 'age'")
    db.execute("SET search_path = ag_catalog, public")
    rows = db.execute("""SELECT * FROM cypher('omneum_context', $$
        MATCH (a:Source)-[d:DEPENDENT]->(b:Source)
        WHERE d.workspace_id = $workspace_id
        RETURN properties(a), properties(d), properties(b)
    $$, %s::agtype) AS (a agtype, d agtype, b agtype)""",
                      (json.dumps({"workspace_id": str(workspace)}),), prepare=True).fetchall()
    return [tuple(json.loads(value) for value in row) for row in rows]


def test_evaluation_run_and_scores(db, prepared):
    args, stored = prepared
    result = args["evaluation"]
    run = save(db, prepared)
    row = db.execute("""SELECT workspace_id,algorithm,algorithm_version,status,parameters,
                               started_at,completed_at FROM public.evaluation_runs WHERE id=%s""",
                     (run,)).fetchone()
    assert isinstance(run, UUID)
    assert row[:4] == (args["workspace_id"], "BRAID", result.convergence.algorithm_version, "completed")
    assert row[4] == {"estimator": asdict(args["estimator"]),
                      "convergence": asdict(result.convergence),
                      "evaluation_latency_ms": result.evaluation_latency_ms}
    assert row[5:] == (None, None)
    sources = dict(db.execute("SELECT source_id,reliability_score FROM public.source_scores WHERE evaluation_run_id=%s", (run,)).fetchall())
    ids_by_source = dict(zip((canonicalize_source(s.kind, s.identifier) for s in args["source_tokens"]),
                             (stored[0].source_id, stored[1].source_id)))
    assert sources == {ids_by_source[canonicalize_source(item.source.kind, item.source.identifier)]: item.reliability
                       for item in result.source_reliability}
    claims = dict((r[0], r[1:]) for r in db.execute("""
        SELECT c.claim_token,s.support_score,s.effective_independent_support,s.dependency_cluster_count
        FROM public.claim_scores s JOIN public.claims c ON c.id=s.claim_id
        WHERE s.evaluation_run_id=%s
    """, (run,)).fetchall())
    assert claims == {args["claim_tokens"][c.claim].value:
                      (c.support, c.estimated_independent_support_count, len(c.dependency_clusters))
                      for c in result.claim_support}


def test_dependency_canonicalization_and_query_back(db, prepared):
    args, stored = prepared
    run = save(db, prepared)
    pair = args["evaluation"].pairwise_dependencies[0]
    a, b, score, coverage, components = db.execute("""
        SELECT source_a_id,source_b_id,dependency_score,signal_coverage,components
        FROM public.source_dependencies WHERE evaluation_run_id=%s
    """, (run,)).fetchone()
    assert a == stored[1].source_id < b == stored[0].source_id
    assert score == pair.dependency
    assert coverage == pair.weighted_signal_coverage
    assert components["signals"] == asdict(pair.signals)
    evidence = components["evidence"]
    assert evidence["source_a_cites_source_b"] == pair.evidence.source_b_cites_source_a
    assert evidence["source_b_cites_source_a"] == pair.evidence.source_a_cites_source_b
    assert evidence["source_a_parent_count"] == pair.evidence.source_b_parent_count
    rows = dependencies(db, args["workspace_id"])
    assert rows == [({"id": str(a), "workspace_id": str(args["workspace_id"])},
                     {"evaluation_run_id": str(run), "workspace_id": str(args["workspace_id"])},
                     {"id": str(b), "workspace_id": str(args["workspace_id"])})]
    assert "private" not in json.dumps(rows)
    # Undirected query starting from the UUID-large endpoint reaches UUID-small.
    row = db.execute("""SELECT * FROM cypher('omneum_context', $$
        MATCH (a:Source)-[d:DEPENDENT]-(b:Source)
        WHERE a.id = $start AND d.evaluation_run_id = $run
        RETURN b.id
    $$, %s::agtype) AS (id agtype)""",
                     (json.dumps({"start": str(b), "run": str(run)}),), prepare=True).fetchall()
    assert row == [(json.dumps(str(a)),)]
    import psycopg
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("""INSERT INTO public.source_dependencies
            (workspace_id,evaluation_run_id,source_a_id,source_b_id,dependency_score)
            VALUES (%s,%s,%s,%s,0.5)""", (args["workspace_id"], run, b, a))
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute("""INSERT INTO public.source_dependencies
            (workspace_id,evaluation_run_id,source_a_id,source_b_id,dependency_score)
            VALUES (%s,%s,%s,%s,0.5)""", (args["workspace_id"], run, a, b))


def test_repeated_evaluation_is_a_new_run(db, prepared):
    first, second = save(db, prepared), save(db, prepared)
    assert first != second
    edges = dependencies(db, prepared[0]["workspace_id"])
    assert {edge[1]["evaluation_run_id"] for edge in edges} == {str(first), str(second)}
    assert len(edges) == 2


def test_same_dependency_projection_does_not_duplicate(db, prepared, monkeypatch):
    original = graph.project_dependency
    def twice(cursor, **kwargs):
        original(cursor, **kwargs)
        original(cursor, **kwargs)
    monkeypatch.setattr(graph, "project_dependency", twice)
    save(db, prepared)
    assert len(dependencies(db, prepared[0]["workspace_id"])) == 1


@pytest.mark.parametrize("autocommit", [True, False])
def test_idle_connection_commits_complete_evaluation(db, prepared, autocommit):
    import os
    import psycopg
    with psycopg.connect(os.environ["OMNEUM_TEST_POSTGRES_DSN"], autocommit=autocommit) as writer:
        run = PostgresStorage(writer).persist_evaluation(**prepared[0])
        assert writer.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
        # A separate connection sees every relational write before writer closes.
        for table, count in (("evaluation_runs", 1), ("source_scores", 2),
                             ("claim_scores", 2), ("source_dependencies", 1)):
            column = "id" if table == "evaluation_runs" else "evaluation_run_id"
            assert db.execute(f"SELECT count(*) FROM public.{table} WHERE {column}=%s",
                              (run,)).fetchone()[0] == count
        assert len(dependencies(db, prepared[0]["workspace_id"])) == 1


def test_outer_rollback_includes_entire_evaluation(db, prepared):
    import psycopg
    with db.transaction():
        run = PostgresStorage(db).persist_evaluation(**prepared[0])
        raise psycopg.Rollback()
    for table in ("source_scores", "claim_scores", "source_dependencies"):
        assert db.execute(f"SELECT count(*) FROM public.{table} WHERE evaluation_run_id=%s", (run,)).fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM public.evaluation_runs WHERE id=%s", (run,)).fetchone()[0] == 0
    assert dependencies(db, prepared[0]["workspace_id"]) == []


def test_projection_error_rolls_back_savepoint_not_caller_work(db, prepared, monkeypatch):
    import psycopg
    original = graph.project_dependency
    def fail(cursor, **kwargs):
        original(cursor, **kwargs)
        cursor.execute("SELECT 1/0")
    monkeypatch.setattr(graph, "project_dependency", fail)
    with db.transaction():
        marker = db.execute("INSERT INTO public.organizations(name) VALUES ('caller-work') RETURNING id").fetchone()[0]
        with pytest.raises(psycopg.errors.DivisionByZero):
            PostgresStorage(db).persist_evaluation(**prepared[0])
        assert db.execute("SELECT count(*) FROM public.organizations WHERE id=%s", (marker,)).fetchone()[0] == 1
        for table in ("evaluation_runs", "source_scores", "claim_scores", "source_dependencies"):
            assert db.execute(f"SELECT count(*) FROM public.{table} WHERE workspace_id=%s",
                              (prepared[0]["workspace_id"],)).fetchone()[0] == 0
    assert dependencies(db, prepared[0]["workspace_id"]) == []
    assert db.execute("SELECT count(*) FROM public.observations WHERE workspace_id=%s",
                      (prepared[0]["workspace_id"],)).fetchone()[0] == 3


def test_workspace_isolation(db, prepared):
    import psycopg
    args, stored = prepared
    other = db.execute("""INSERT INTO public.workspaces(organization_id,name)
        SELECT organization_id,'other' FROM public.workspaces WHERE id=%s RETURNING id""",
                       (args["workspace_id"],)).fetchone()[0]
    with db.transaction():
        with pytest.raises(ValueError, match="sources must already exist"):
            PostgresStorage(db).persist_evaluation(**{**args, "workspace_id": other})
    other_run = db.execute("""INSERT INTO public.evaluation_runs(workspace_id,algorithm_version)
                             VALUES (%s,'test') RETURNING id""", (other,)).fetchone()[0]
    a, b = sorted((stored[0].source_id, stored[1].source_id))
    attempts = (
        ("INSERT INTO public.source_scores(workspace_id,evaluation_run_id,source_id,reliability_score) VALUES (%s,%s,%s,0.5)", (other, other_run, a)),
        ("INSERT INTO public.claim_scores(workspace_id,evaluation_run_id,claim_id,support_score) VALUES (%s,%s,%s,0.5)", (other, other_run, stored[0].claim_id)),
        ("INSERT INTO public.source_dependencies(workspace_id,evaluation_run_id,source_a_id,source_b_id,dependency_score) VALUES (%s,%s,%s,%s,0.5)", (other, other_run, a, b)),
        ("INSERT INTO public.source_scores(workspace_id,evaluation_run_id,source_id,reliability_score) VALUES (%s,%s,%s,0.5)", (args["workspace_id"], other_run, a)),
    )
    for query, values in attempts:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            db.execute(query, values)
    # The same VOPRF tokens resolve to distinct existing rows in another workspace.
    for source, tok in args["source_tokens"].items():
        db.execute("INSERT INTO public.sources(workspace_id,source_token) VALUES (%s,%s)", (other, tok.value))
    for tok in args["claim_tokens"].values():
        db.execute("INSERT INTO public.claims(workspace_id,claim_token) VALUES (%s,%s)", (other, tok.value))
    with db.transaction():
        run = PostgresStorage(db).persist_evaluation(**{**args, "workspace_id": other})
    assert db.execute("SELECT count(*) FROM public.source_scores WHERE evaluation_run_id=%s AND source_id=ANY(%s)",
                      (run, [a, b])).fetchone()[0] == 0
    assert len(dependencies(db, other)) == 1
    assert dependencies(db, args["workspace_id"]) == []


def test_missing_claim_and_invalid_tokens_leave_no_run(db, prepared):
    args = prepared[0]
    claims = dict(args["claim_tokens"])
    claim = next(iter(claims))
    claims[claim] = replace(claims[claim], value=b"x" * 64)
    with db.transaction():
        with pytest.raises(ValueError, match="claims must already exist"):
            PostgresStorage(db).persist_evaluation(**{**args, "claim_tokens": claims})
        with pytest.raises(ValueError, match="exactly cover"):
            PostgresStorage(db).persist_evaluation(**{**args, "source_tokens": {}})
    assert db.execute("SELECT count(*) FROM public.evaluation_runs WHERE workspace_id=%s", (args["workspace_id"],)).fetchone()[0] == 0


def test_no_clusters_or_evidence_remain_null(db, prepared):
    args = prepared[0]
    evaluation = replace(args["evaluation"], dependency_cluster_threshold=None,
                         claim_support=tuple(replace(c, dependency_clusters=None) for c in args["evaluation"].claim_support),
                         pairwise_dependencies=tuple(replace(p, evidence=None) for p in args["evaluation"].pairwise_dependencies))
    with db.transaction():
        run = PostgresStorage(db).persist_evaluation(**{**args, "evaluation": evaluation,
            "estimator": replace(args["estimator"], dependency_cluster_threshold=None)})
    assert all(r[0] is None for r in db.execute("SELECT dependency_cluster_count FROM public.claim_scores WHERE evaluation_run_id=%s", (run,)).fetchall())
    assert db.execute("SELECT components FROM public.source_dependencies WHERE evaluation_run_id=%s", (run,)).fetchone()[0]["evidence"] is None


@pytest.mark.parametrize("existing", ["valid", "cross_workspace", "reverse_pair"])
def test_migration_upgrade_backfill_and_validation(db, existing):
    import os
    from pathlib import Path
    import subprocess
    from psycopg import connect, sql
    from psycopg.conninfo import make_conninfo

    name = "omneum_history_migration_" + uuid4().hex
    db.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name)))
    dsn = make_conninfo(os.environ["OMNEUM_TEST_POSTGRES_DSN"], dbname=name)
    root = Path(__file__).resolve().parents[1]

    def migrate(*files):
        args = ["psql", "-X", "--dbname", dsn, "-v", "ON_ERROR_STOP=1"]
        for filename in files:
            args.extend(["-f", str(root / "migrations" / filename)])
        return subprocess.run(args, capture_output=True, text=True)

    try:
        bootstrap = migrate("001_initial_schema.sql", "002_context_graph.sql")
        assert bootstrap.returncode == 0, bootstrap.stderr
        with connect(dsn, autocommit=True) as clean:
            org = clean.execute("INSERT INTO public.organizations(name) VALUES ('upgrade') RETURNING id").fetchone()[0]
            ws = clean.execute("INSERT INTO public.workspaces(organization_id,name) VALUES (%s,'one') RETURNING id", (org,)).fetchone()[0]
            other = clean.execute("INSERT INTO public.workspaces(organization_id,name) VALUES (%s,'two') RETURNING id", (org,)).fetchone()[0]
            run = clean.execute("INSERT INTO public.evaluation_runs(workspace_id,algorithm_version) VALUES (%s,'existing') RETURNING id", (ws,)).fetchone()[0]
            a, b = sorted((uuid4(), uuid4()))
            clean.execute("INSERT INTO public.sources(id,workspace_id,source_token) VALUES (%s,%s,%s),(%s,%s,%s)",
                          (a, ws, b"a", b, ws, b"b"))
            claim = clean.execute("INSERT INTO public.claims(workspace_id,claim_token) VALUES (%s,%s) RETURNING id",
                                  (other if existing == "cross_workspace" else ws, b"c")).fetchone()[0]
            clean.execute("INSERT INTO public.source_scores(evaluation_run_id,source_id,reliability_score) VALUES (%s,%s,0.75)", (run, a))
            clean.execute("INSERT INTO public.claim_scores(evaluation_run_id,claim_id,support_score) VALUES (%s,%s,0.6)", (run, claim))
            first, second = (b, a) if existing == "reverse_pair" else (a, b)
            clean.execute("""INSERT INTO public.source_dependencies
                (evaluation_run_id,source_a_id,source_b_id,dependency_score,signal_coverage,components)
                VALUES (%s,%s,%s,0.4,0.8,'{"retained": true}')""", (run, first, second))
            result = migrate("003_evaluation_history.sql")
            if existing == "valid":
                assert result.returncode == 0, result.stderr
                rerun = migrate("003_evaluation_history.sql")
                assert rerun.returncode == 0, rerun.stderr
                for table in ("source_scores", "claim_scores", "source_dependencies"):
                    assert clean.execute(f"SELECT workspace_id FROM public.{table}").fetchall() == [(ws,)]
                assert clean.execute("SELECT dependency_score,signal_coverage,components FROM public.source_dependencies").fetchone() == (0.4, 0.8, {"retained": True})
                # Original run delete cascade remains intact.
                clean.execute("DELETE FROM public.evaluation_runs WHERE id=%s", (run,))
                for table in ("source_scores", "claim_scores", "source_dependencies"):
                    assert clean.execute(f"SELECT count(*) FROM public.{table}").fetchone()[0] == 0
            else:
                assert result.returncode != 0
                constraint = ("claim_scores_workspace_claim_fkey" if existing == "cross_workspace"
                              else "source_dependencies_canonical_pair_check")
                assert constraint in result.stderr
                # All DDL/backfill rolls back, leaving prior results untouched.
                assert clean.execute("""SELECT count(*) FROM information_schema.columns
                    WHERE table_schema='public' AND table_name='source_scores'
                      AND column_name='workspace_id'""").fetchone()[0] == 0
                assert clean.execute("SELECT source_a_id,source_b_id FROM public.source_dependencies").fetchone() == (first, second)
    finally:
        db.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


def test_concurrent_evaluations_reuse_identities(db, prepared):
    from concurrent.futures import ThreadPoolExecutor
    import os
    import psycopg

    def write(_):
        with psycopg.connect(os.environ["OMNEUM_TEST_POSTGRES_DSN"], autocommit=True) as writer:
            writer.execute("SET statement_timeout = '15s'")
            return PostgresStorage(writer).persist_evaluation(**prepared[0])

    with ThreadPoolExecutor(max_workers=4) as pool:
        runs = list(pool.map(write, range(4)))
    assert len(set(runs)) == 4
    ws = prepared[0]["workspace_id"]
    for table, count in (("sources", 2), ("claims", 2), ("observations", 3),
                         ("source_scores", 8), ("claim_scores", 8),
                         ("source_dependencies", 4)):
        assert db.execute(f"SELECT count(*) FROM public.{table} WHERE workspace_id=%s",
                          (ws,)).fetchone()[0] == count
    edges = dependencies(db, ws)
    assert len(edges) == 4
    assert {edge[1]["evaluation_run_id"] for edge in edges} == set(map(str, runs))


def test_caller_commit_controls_visibility(db, prepared):
    import os
    import psycopg
    with psycopg.connect(os.environ["OMNEUM_TEST_POSTGRES_DSN"], autocommit=True) as reader:
        with db.transaction():
            run = PostgresStorage(db).persist_evaluation(**prepared[0])
            assert reader.execute("SELECT count(*) FROM public.evaluation_runs WHERE id=%s",
                                  (run,)).fetchone()[0] == 0
            assert dependencies(reader, prepared[0]["workspace_id"]) == []
        assert reader.execute("SELECT count(*) FROM public.evaluation_runs WHERE id=%s",
                              (run,)).fetchone()[0] == 1
        assert len(dependencies(reader, prepared[0]["workspace_id"])) == 1


@pytest.mark.parametrize("autocommit", [True, False])
def test_idle_projection_failure_is_atomic(db, prepared, monkeypatch, autocommit):
    import os
    import psycopg
    original = graph.project_dependency

    def fail(cursor, **kwargs):
        original(cursor, **kwargs)
        cursor.execute("SELECT 1/0")

    monkeypatch.setattr(graph, "project_dependency", fail)
    with psycopg.connect(os.environ["OMNEUM_TEST_POSTGRES_DSN"], autocommit=autocommit) as writer:
        with pytest.raises(psycopg.errors.DivisionByZero):
            PostgresStorage(writer).persist_evaluation(**prepared[0])
        assert writer.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
    for table in ("evaluation_runs", "source_scores", "claim_scores", "source_dependencies"):
        assert db.execute(f"SELECT count(*) FROM public.{table} WHERE workspace_id=%s",
                          (prepared[0]["workspace_id"],)).fetchone()[0] == 0
    assert dependencies(db, prepared[0]["workspace_id"]) == []
