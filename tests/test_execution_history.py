import asyncio
import json
import logging
import sqlite3
from uuid import UUID

import pytest

from omneum import LocalPersistenceConfig, LocalPersistenceError, OmneumClient, SQLiteStorage
from omneum.metrics import _execution_telemetry
from omneum.storage.base import EXECUTION_FIELDS
from test_agent_result import mapped_chunks
from test_local_persistence import runtime
from test_storage_evaluation import computed
from test_storage import db, workspace


def prepare(runtime, storage, *, collect=False, budget=1000, chunks=None):
    config, evaluator, observations, estimator = runtime
    client = OmneumClient(config, evaluator, local_persistence=LocalPersistenceConfig(storage))
    expected = computed_chunks(runtime) if chunks is None else chunks
    return asyncio.run(client.prepare_context(observations, expected, estimator=estimator,
        token_budget=budget, collect_telemetry=collect))


def computed_chunks(runtime):
    from omneum.client import _evaluate_context
    return mapped_chunks(_evaluate_context(runtime[2], estimator=runtime[3]))


def history(storage):
    with storage.transaction() as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute('SELECT * FROM execution_history ORDER BY rowid')]


def test_automatic_history_and_restart(runtime, tmp_path, caplog, capsys):
    caplog.set_level(logging.INFO, logger='omneum.execution')
    storage = SQLiteStorage(tmp_path / 'omneum.db')
    first = prepare(runtime, storage)
    assert not [r for r in caplog.records if r.name == 'omneum.execution']
    assert capsys.readouterr() == ('', '')
    second = prepare(runtime, SQLiteStorage(storage.path), collect=True)
    assert first == second
    assert json.loads(json.dumps(first, allow_nan=False)) == first
    assert set(first) == {'evaluation', 'selection', 'packed_chunk_ids', 'chunks', 'context'}
    rows = history(SQLiteStorage(storage.path))
    assert len(rows) == 2
    assert len({row['id'] for row in rows}) == len({row['evaluation_run_id'] for row in rows}) == 2
    for row in rows:
        UUID(row['id'])
        UUID(row['evaluation_run_id'])
        assert row['created_at'].endswith('Z')
        for name in EXECUTION_FIELDS:
            if name.endswith('_ms'):
                assert row[name] is None or row[name] >= 0
        assert row['sdk_end_to_end_latency_ms'] >= row['evaluation_latency_ms']
        assert row['evaluation_latency_ms'] >= row['local_inference_latency_ms']
        assert row['cpu_time_scope'] == 'sdk_process_during_evaluation'
        assert row['peak_memory_scope'] == 'sdk_process_lifetime_peak_rss'
        for name in ('input_tokens', 'selected_tokens', 'token_budget', 'reduction_ratio'):
            assert row[name] == first['selection'][name]
        assert row['peak_memory_bytes'] is None or row['peak_memory_bytes'] >= 0
    record = next(r.execution for r in caplog.records if r.name == 'omneum.execution')
    assert record['execution_history_id'] == rows[1]['id']
    assert record['evaluation_run_id'] == rows[1]['evaluation_run_id']
    for name in EXECUTION_FIELDS:
        assert record[name] == rows[1][name]
    assert 'Original' not in json.dumps(rows) + json.dumps(record)
    with storage.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM evaluation_runs').fetchone()[0] == 2
        assert not connection.execute('PRAGMA foreign_key_check').fetchall()
        with pytest.raises(sqlite3.IntegrityError):
            storage.persist_execution(workspace_id=LocalPersistenceConfig(storage).workspace_id,
                evaluation_run_id=UUID(rows[0]['evaluation_run_id']),
                execution={name: rows[0][name] for name in EXECUTION_FIELDS})
    # These are actual values for the release verification report, not fixtures.
    print('execution_history row:', json.dumps(rows[1], sort_keys=True))
    print('structured execution log:', json.dumps(record, sort_keys=True))


def test_failed_preparation_preserves_evaluation_only(runtime, tmp_path):
    storage = SQLiteStorage(tmp_path / 'omneum.db')
    with pytest.raises(ValueError, match='budget'):
        prepare(runtime, storage, budget=-1)
    assert history(storage) == []
    with storage.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM evaluation_runs').fetchone()[0] == 1
        assert connection.execute('SELECT count(*) FROM source_scores').fetchone()[0] == 2
    prepare(runtime, storage)
    rows = history(storage)
    with storage.transaction() as connection:
        latest = connection.execute('SELECT id FROM evaluation_runs ORDER BY rowid DESC LIMIT 1').fetchone()[0]
    assert len(rows) == 1 and rows[0]['evaluation_run_id'] == latest
    assert _execution_telemetry.get() is None


def test_failed_history_append_rolls_back(runtime, tmp_path, monkeypatch):
    storage = SQLiteStorage(tmp_path / 'omneum.db')
    original = SQLiteStorage.persist_execution

    def fail(self, **kwargs):
        with self.transaction():
            original(self, **kwargs)
            raise RuntimeError('private database details must not escape')

    monkeypatch.setattr(SQLiteStorage, 'persist_execution', fail)
    with pytest.raises(LocalPersistenceError, match='execution history') as error:
        prepare(runtime, storage)
    assert 'private' not in str(error.value)
    assert isinstance(error.value.evaluation_run_id, UUID)
    assert history(storage) == []
    with storage.transaction() as connection:
        assert connection.execute('SELECT id FROM evaluation_runs').fetchone()[0] == str(error.value.evaluation_run_id)
    assert _execution_telemetry.get() is None


def test_concurrent_preparations_keep_run_associations(runtime, tmp_path):
    config, evaluator, observations, estimator = runtime
    storage = SQLiteStorage(tmp_path / 'omneum.db')
    client = OmneumClient(config, evaluator, local_persistence=LocalPersistenceConfig(storage))
    chunks = computed_chunks(runtime)

    async def run():
        return await asyncio.gather(*(client.prepare_context(observations, chunks,
            estimator=estimator, token_budget=budget) for budget in (0, 1000)))

    results = asyncio.run(run())
    rows = history(storage)
    assert len(rows) == 2 and len({r['evaluation_run_id'] for r in rows}) == 2
    by_budget = {row['token_budget']: row for row in rows}
    for result in results:
        selection = result['selection']
        for field in ('input_tokens', 'selected_tokens', 'token_budget', 'reduction_ratio'):
            assert selection[field] == by_budget[selection['token_budget']][field]
    assert results[0]['evaluation'] == results[1]['evaluation']


def test_standard_stderr_and_file_handlers(runtime, tmp_path, capsys):
    storage = SQLiteStorage(tmp_path / 'omneum.db')
    logger = logging.getLogger('omneum.execution')
    previous = logger.level
    stderr = logging.StreamHandler()
    file = logging.FileHandler(tmp_path / 'diagnostics.log')
    formatter = logging.Formatter('%(message)s %(execution)s')
    for handler in (stderr, file):
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        silent = prepare(runtime, storage)
        assert capsys.readouterr() == ('', '')
        logged = prepare(runtime, storage, collect=True)
        captured = capsys.readouterr()
        assert captured.out == ''
        assert captured.err.count('Context prepared') == 1
        assert (tmp_path / 'diagnostics.log').read_text().count('Context prepared') == 1
        assert silent == logged
        assert len(history(storage)) == 2
        assert 'Original' not in captured.err
    finally:
        for handler in (stderr, file):
            logger.removeHandler(handler)
            handler.close()
        logger.setLevel(previous)


def test_postgres_execution_history(runtime, db, workspace):
    from omneum.storage import PostgresStorage
    from pathlib import Path
    db.execute(Path('migrations/006_execution_history.sql').read_text())
    db.execute(Path('migrations/006_execution_history.sql').read_text())
    storage = PostgresStorage(db)
    config, evaluator, observations, estimator = runtime
    client = OmneumClient(config, evaluator, local_persistence=LocalPersistenceConfig(storage, workspace))
    result = asyncio.run(client.prepare_context(observations, computed_chunks(runtime),
        estimator=estimator, token_budget=1000))
    row = db.execute('SELECT evaluation_run_id,selected_tokens FROM public.execution_history WHERE workspace_id=%s', (workspace,)).fetchone()
    assert row[1] == result['selection']['selected_tokens']
    assert db.execute('SELECT count(*) FROM public.evaluation_runs WHERE id=%s AND workspace_id=%s', (row[0], workspace)).fetchone() == (1,)


def test_empty_context_history(runtime, tmp_path):
    storage = SQLiteStorage(tmp_path / 'omneum.db')
    result = prepare(runtime, storage, budget=0, chunks=[])
    row = history(storage)[0]
    assert row['input_tokens'] == row['selected_tokens'] == row['token_budget'] == 0
    assert row['reduction_ratio'] == result['selection']['reduction_ratio'] == 0.0
    assert result['context'] == ''


def test_default_sdk_history_over_real_mcp(example_daemon, computed, monkeypatch, caplog, capfd):
    import os
    import sys
    from copy import deepcopy
    from omneum import OmneumClientConfig, open_stdio_client
    from omneum.mcp import ClientSession, StdioServerParameters
    from omneum.paths import get_context_db_path

    path = get_context_db_path()
    assert path.name == 'omneum.db' and not path.exists()
    observations, estimator = computed[4], computed[3]
    chunks = mapped_chunks(computed[0])
    requests = []
    original = ClientSession.call_tool

    async def track(self, name, arguments=None, *args, **kwargs):
        if name == 'evaluate_context':
            requests.append(deepcopy(arguments))
        return await original(self, name, arguments, *args, **kwargs)

    monkeypatch.setattr(ClientSession, 'call_tool', track)
    caplog.set_level(logging.INFO, logger='omneum.execution')

    async def run():
        server = StdioServerParameters(command=sys.executable, args=['-m', 'omneum.server'], env=dict(os.environ))
        async with open_stdio_client(OmneumClientConfig.from_local_deployment(), server) as client:
            assert path.exists()
            assert history(SQLiteStorage(path)) == []
            quiet = await client.prepare_context(observations, chunks, estimator=estimator, token_budget=1000)
            assert not [r for r in caplog.records if r.name == 'omneum.execution']
            logged = await client.prepare_context(observations, chunks, estimator=estimator,
                token_budget=1000, collect_telemetry=True)
        assert quiet == logged
        return quiet

    result = asyncio.run(run())
    assert json.loads(json.dumps(result, allow_nan=False)) == result
    assert capfd.readouterr() == ('', '')
    assert len(requests) == 2 and requests[0] == requests[1]
    assert all(chunk['raw_text'] not in json.dumps(requests) for chunk in chunks)
    rows = history(SQLiteStorage(path))
    assert len(rows) == 2
    assert len([r for r in caplog.records if r.name == 'omneum.execution']) == 1
    with SQLiteStorage(path).transaction() as connection:
        assert connection.execute('SELECT count(*) FROM evaluation_runs').fetchone() == (2,)
        assert not connection.execute('PRAGMA foreign_key_check').fetchall()
