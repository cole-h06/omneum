"""Client-local persistence across direct and real MCP stdio evaluation paths."""

import asyncio
from dataclasses import asdict, replace
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest
from omneum.mcp import StdioServerParameters

from omneum import (
    ContextMapper, LocalPersistenceConfig, LocalPersistenceError,
    OmneumClient, OmneumClientConfig, open_stdio_client,
)
from omneum.client import ContextEvaluationTransportError
from omneum.storage import PostgresStorage, graph
from omneum.tools.evaluate_context import AssertionEvaluationService
from test_client import DEPLOYMENT_ID, PRIVATE_KEY, LocalEvaluator, make_config, make_server
from test_evaluate_context import make_state
from test_storage import db, workspace, query_graph
from test_storage_evaluation import computed, dependencies
from stdio_state import isolated_deployment_environment


@pytest.fixture
def runtime(tmp_path, computed):
    server = make_server(tmp_path)
    service = AssertionEvaluationService(make_state(server=server))

    class Evaluator(LocalEvaluator):
        context_calls = 0

        async def evaluate_context(self, request):
            self.context_calls += 1
            return await service.evaluate(request)

    evaluator = Evaluator(server)
    observations = tuple(replace(o, metadata={"private": [o.observation_id]})
                         for o in computed[4])
    try:
        yield make_config(server), evaluator, observations, computed[3]
    finally:
        service.close()


def evaluate(runtime, persistence=None):
    config, evaluator, observations, estimator = runtime
    return asyncio.run(OmneumClient(config, evaluator, local_persistence=persistence)
                       .evaluate_context(observations, estimator=estimator))


def counts(db, ws):
    return {table: db.execute(f"SELECT count(*) FROM public.{table} WHERE workspace_id=%s",
                             (ws,)).fetchone()[0]
            for table in ("sources", "claims", "observations", "evaluation_runs",
                          "source_scores", "claim_scores", "source_dependencies")}


def test_explicitly_disabled_evaluation(runtime, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("disabled persistence was called")

    monkeypatch.setattr(LocalPersistenceConfig, "_persist", forbidden)
    result = evaluate(runtime)
    assert len(result.source_reliability) == 2
    assert len(result.claim_support) == 2
    assert runtime[1].context_calls == 1


def test_no_psycopg_disabled_and_explicit_failure():
    script = '''
import importlib.abc
import sys
class NoPostgres(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname == "psycopg" or fullname.startswith("psycopg."):
            raise ModuleNotFoundError("postgres extra deliberately unavailable")
sys.meta_path.insert(0, NoPostgres())
import pytest
sys.exit(pytest.main(["-q",
    "tests/test_local_persistence.py::test_explicitly_disabled_evaluation",
    "tests/test_local_persistence.py::test_enabled_missing_driver_is_persistence_error"]))
'''
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_enabled_missing_driver_is_persistence_error(runtime, monkeypatch):
    from contextlib import nullcontext
    import builtins
    original = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "psycopg" or name.startswith("psycopg."):
            raise ModuleNotFoundError("unavailable")
        return original(name, *args, **kwargs)

    class Connection:
        def transaction(self):
            return nullcontext()

    monkeypatch.setattr(builtins, "__import__", blocked)
    config = LocalPersistenceConfig(PostgresStorage(Connection()), uuid4())
    with pytest.raises(LocalPersistenceError) as error:
        evaluate(runtime, config)
    assert len(error.value.evaluation.claim_support) == 2
    assert "private" not in str(error.value)


def test_disabled_writes_nothing(db, workspace, runtime):
    evaluate(runtime)
    assert not any(counts(db, workspace).values())
    assert dependencies(db, workspace) == []


def test_complete_evaluation_and_identity_reuse(db, workspace, runtime, computed, monkeypatch):
    import omneum.client as client_module
    calls = {"infer": 0, "estimate_dependencies": 0}
    for name in calls:
        function = getattr(client_module, name)

        def count(*args, _name=name, _function=function, **kwargs):
            calls[_name] += 1
            return _function(*args, **kwargs)

        monkeypatch.setattr(client_module, name, count)
    config = LocalPersistenceConfig(PostgresStorage(db), workspace)
    original = PostgresStorage.persist_evaluation
    captured = []

    def capture(self, **kwargs):
        captured.append(kwargs)
        return original(self, **kwargs)

    monkeypatch.setattr(PostgresStorage, "persist_evaluation", capture)
    result = evaluate(runtime, config)
    assert captured[0]["evaluation"] is result
    assert captured[0]["estimator"] is runtime[3]
    assert counts(db, workspace) == dict(sources=2, claims=2, observations=3,
        evaluation_runs=1, source_scores=2, claim_scores=2, source_dependencies=1)
    # Same real VOPRF key as the slice 2 fixture, with no token reissuance for storage.
    assert set(t.value for t in captured[0]["source_tokens"].values()) == set(t.value for t in computed[1].values())
    assert set(t.value for t in captured[0]["claim_tokens"].values()) == set(t.value for t in computed[2].values())
    assert len(runtime[1].requests) == 6  # two Sources, two Attributes, two Claims
    assert runtime[1].context_calls == 1
    assert calls == {"infer": 1, "estimate_dependencies": 1}
    source_ids = db.execute("SELECT id FROM public.sources WHERE workspace_id=%s ORDER BY id", (workspace,)).fetchall()
    claim_ids = db.execute("SELECT id FROM public.claims WHERE workspace_id=%s ORDER BY id", (workspace,)).fetchall()
    run, params = db.execute("SELECT id,parameters FROM public.evaluation_runs WHERE workspace_id=%s", (workspace,)).fetchone()
    assert params["convergence"] == asdict(result.convergence)
    assert params["evaluation_latency_ms"] == result.evaluation_latency_ms
    source_scores = dict(db.execute("""SELECT s.source_token,r.reliability_score
        FROM public.source_scores r JOIN public.sources s ON s.id=r.source_id
        WHERE r.evaluation_run_id=%s""", (run,)).fetchall())
    assert source_scores == {captured[0]["source_tokens"][item.source].value: item.reliability
                             for item in result.source_reliability}
    claim_scores = dict(db.execute("""SELECT c.claim_token,r.support_score
        FROM public.claim_scores r JOIN public.claims c ON c.id=r.claim_id
        WHERE r.evaluation_run_id=%s""", (run,)).fetchall())
    assert claim_scores == {captured[0]["claim_tokens"][item.claim].value: item.support
                            for item in result.claim_support}
    assert db.execute("SELECT dependency_score,signal_coverage FROM public.source_dependencies WHERE evaluation_run_id=%s",
                      (run,)).fetchone() == (result.pairwise_dependencies[0].dependency,
                                           result.pairwise_dependencies[0].weighted_signal_coverage)
    assert db.execute("SELECT metadata FROM public.observations WHERE workspace_id=%s ORDER BY metadata::text",
                      (workspace,)).fetchall() == [(o.metadata,) for o in runtime[2]]
    edges = [r for r in query_graph(db) if r[0]["workspace_id"] == str(workspace)]
    assert len(edges) == 3
    assert all(set(properties) == {"id", "workspace_id"} for row in edges for properties in row)
    assert len(dependencies(db, workspace)) == 1
    evaluate(runtime, config)
    assert counts(db, workspace) == dict(sources=2, claims=2, observations=6,
        evaluation_runs=2, source_scores=4, claim_scores=4, source_dependencies=2)
    assert db.execute("SELECT id FROM public.sources WHERE workspace_id=%s ORDER BY id", (workspace,)).fetchall() == source_ids
    assert db.execute("SELECT id FROM public.claims WHERE workspace_id=%s ORDER BY id", (workspace,)).fetchall() == claim_ids
    assert len(dependencies(db, workspace)) == 2


@pytest.mark.parametrize("failure", ["observed", "dependent", "relational"])
def test_failure_rolls_back_complete_evaluation(db, workspace, runtime, monkeypatch, failure):
    if failure == "relational":
        original = PostgresStorage.persist_evaluation

        def fail(self, **kwargs):
            original(self, **kwargs)
            self.connection.execute("INSERT INTO public.source_scores(evaluation_run_id) VALUES (NULL)")

        monkeypatch.setattr(PostgresStorage, "persist_evaluation", fail)
    else:
        name = "project_observation" if failure == "observed" else "project_dependency"
        original = getattr(graph, name)

        def fail(cursor, **kwargs):
            original(cursor, **kwargs)
            cursor.execute("SELECT 1/0")

        monkeypatch.setattr(graph, name, fail)
    with db.transaction():
        marker = db.execute("INSERT INTO public.organizations(name) VALUES ('caller') RETURNING id").fetchone()[0]
        with pytest.raises(LocalPersistenceError) as caught:
            evaluate(runtime, LocalPersistenceConfig(PostgresStorage(db), workspace))
        assert len(caught.value.evaluation.source_reliability) == 2
        assert not isinstance(caught.value, ContextEvaluationTransportError)
        assert db.execute("SELECT count(*) FROM public.organizations WHERE id=%s", (marker,)).fetchone()[0] == 1
        assert not any(counts(db, workspace).values())
    assert dependencies(db, workspace) == []
    assert not [r for r in query_graph(db) if r[0]["workspace_id"] == str(workspace)]


def test_workspace_and_outer_rollback(db, workspace, runtime):
    import psycopg
    other = db.execute("""INSERT INTO public.workspaces(organization_id,name)
        SELECT organization_id,'other' FROM public.workspaces WHERE id=%s RETURNING id""", (workspace,)).fetchone()[0]
    evaluate(runtime, LocalPersistenceConfig(PostgresStorage(db), workspace))
    with db.transaction():
        evaluate(runtime, LocalPersistenceConfig(PostgresStorage(db), other))
        raise psycopg.Rollback()
    assert not any(counts(db, other).values())
    evaluate(runtime, LocalPersistenceConfig(PostgresStorage(db), other))
    for table, token in (("sources", "source_token"), ("claims", "claim_token")):
        rows = db.execute(f"SELECT {token},array_agg(id) FROM public.{table} WHERE workspace_id=ANY(%s) GROUP BY {token}",
                          ([workspace, other],)).fetchall()
        assert len(rows) == 2 and all(len(set(ids)) == 2 for _, ids in rows)
    assert len(dependencies(db, workspace)) == len(dependencies(db, other)) == 1


def test_mapped_uses_same_persistence(db, workspace, runtime):
    config, evaluator, observations, estimator = runtime
    mapper = ContextMapper(source="source", entity_namespace="claim.entity_namespace",
        entity="claim.entity", attribute="claim.attribute", value="claim.value",
        observation_id="observation_id", observed_at="observed_at")
    result = asyncio.run(OmneumClient(config, evaluator,
        local_persistence=LocalPersistenceConfig(PostgresStorage(db), workspace))
        .evaluate_mapped(observations, mapper, estimator=estimator))
    assert len(result.claim_support) == 2
    assert counts(db, workspace)["evaluation_runs"] == 1


@pytest.mark.parametrize("mode", ["disabled", "enabled", "failure"])
def test_real_mcp_local_persistence(db, workspace, tmp_path, computed, monkeypatch, mode):
    enabled = mode != "disabled"
    if mode == "failure":
        original = graph.project_dependency

        def fail(cursor, **kwargs):
            original(cursor, **kwargs)
            cursor.execute("SELECT 1/0")

        monkeypatch.setattr(graph, "project_dependency", fail)
    environment, public_key, _ = isolated_deployment_environment(tmp_path, DEPLOYMENT_ID, PRIVATE_KEY)
    parameters = StdioServerParameters(command=sys.executable, args=["-m", "omneum.server"],
        cwd=Path(__file__).resolve().parents[1], env=environment)
    config = OmneumClientConfig(DEPLOYMENT_ID, 1, "voprf", "ristretto255-SHA512", 1, public_key)
    local = LocalPersistenceConfig(PostgresStorage(db), workspace) if enabled else None

    async def run():
        async with open_stdio_client(config, parameters, local_persistence=local) as client:
            if mode == "failure":
                with pytest.raises(LocalPersistenceError) as caught:
                    await client.evaluate_context(computed[4], estimator=computed[3])
                return caught.value.evaluation
            return await client.evaluate_context(computed[4], estimator=computed[3])

    result = asyncio.run(run())
    assert len(result.claim_support) == 2
    assert counts(db, workspace) == (dict(sources=2, claims=2, observations=3,
        evaluation_runs=1, source_scores=2, claim_scores=2, source_dependencies=1)
        if mode == "enabled" else dict.fromkeys(counts(db, workspace), 0))
    assert len(dependencies(db, workspace)) == int(mode == "enabled")


def test_evaluation_failure_never_persists(db, workspace, runtime, monkeypatch):
    async def fail(request):
        raise OSError("evaluation transport failed")

    monkeypatch.setattr(runtime[1], "evaluate_context", fail)
    with pytest.raises(ContextEvaluationTransportError):
        evaluate(runtime, LocalPersistenceConfig(PostgresStorage(db), workspace))
    assert not any(counts(db, workspace).values())
