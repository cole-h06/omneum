import asyncio
import json
import logging
from dataclasses import replace

import pytest

from omneum import LocalPersistenceConfig, OmneumClient, SQLiteStorage
from omneum.metrics import HumanExecutionFormatter, JsonExecutionFormatter
from test_execution_history import computed_chunks, history
from test_local_persistence import runtime
from test_storage_evaluation import computed


def test_reuse_persists_once_and_keeps_measurements(runtime, tmp_path, caplog):
    config, evaluator, observations, estimator = runtime
    storage = SQLiteStorage(tmp_path / 'omneum.db')
    client = OmneumClient(config, evaluator, local_persistence=LocalPersistenceConfig(storage))
    caplog.set_level(logging.INFO, logger='omneum.execution')

    async def run():
        evaluation = await client.evaluate_context(observations, estimator=estimator)
        assert not history(storage)
        with storage.transaction() as connection:
            assert connection.execute('SELECT count(*) FROM evaluation_runs').fetchone()[0] == 1
        result = await client.prepare_context(observations, computed_chunks(runtime), estimator=estimator,
            token_budget=100, evaluation=evaluation, include_telemetry=True, collect_telemetry=True)
        with pytest.raises(ValueError, match='completed context preparation'):
            await client.prepare_context(observations, computed_chunks(runtime), estimator=estimator,
                token_budget=100, evaluation=evaluation)
        return evaluation, result

    evaluation, result = asyncio.run(run())
    assert evaluator.context_calls == 1
    rows = history(storage)
    assert len(rows) == 1
    assert rows[0]['evaluation_run_id'] == evaluation.evaluation_run_id
    assert rows[0]['selected_tokens'] == result['selection']['selected_tokens']
    assert rows[0]['sdk_end_to_end_latency_ms'] >= evaluation.evaluation_latency_ms
    assert result['telemetry']['cpu_time_ms'] is not None
    assert result['telemetry']['cpu_time_scope'] == 'sdk_process_during_evaluation'
    assert result['telemetry']['peak_memory_scope'] == 'sdk_process_lifetime_peak_rss'
    record, = [record for record in caplog.records if record.name == 'omneum.execution']
    projected = json.loads(JsonExecutionFormatter().format(record))
    assert set(projected) == {'event', 'timestamp', 'evaluation_run_id', 'execution'}
    assert projected['event'] == 'omneum.execution'
    assert projected['evaluation_run_id'] == evaluation.evaluation_run_id
    assert projected['execution']['sdk_duration_ms'] == rows[0]['sdk_end_to_end_latency_ms']
    assert projected['execution']['sdk_cpu_time_ms'] == rows[0]['cpu_time_ms']
    assert 'Original' not in JsonExecutionFormatter().format(record)
    assert 'SDK CPU time:' in HumanExecutionFormatter().format(record)
    json.dumps(result, allow_nan=False)
    print('structured execution:', JsonExecutionFormatter().format(record))
    print('human execution:\n' + HumanExecutionFormatter().format(record))
    print('execution history:', json.dumps(rows[0], sort_keys=True))


def test_reuse_validates_inputs_and_storage(runtime, tmp_path):
    config, evaluator, observations, estimator = runtime
    client = OmneumClient(config, evaluator, local_persistence=None)

    async def run():
        evaluation = await client.evaluate_context(observations, estimator=estimator)
        with pytest.raises(ValueError, match='inputs or deployment'):
            await client.prepare_context(observations[:-1], computed_chunks(runtime), estimator=estimator,
                token_budget=100, evaluation=evaluation)
        with pytest.raises(ValueError, match='unchanged SDK evaluation'):
            await client.prepare_context(observations, computed_chunks(runtime), estimator=estimator,
                token_budget=100, evaluation=replace(evaluation))
        persisted = OmneumClient(config, evaluator,
            local_persistence=LocalPersistenceConfig(SQLiteStorage(tmp_path / 'omneum.db')))
        with pytest.raises(ValueError, match='persistence destination'):
            await persisted.prepare_context(observations, computed_chunks(runtime), estimator=estimator,
                token_budget=100, evaluation=evaluation)
        results = [await client.prepare_context(observations, computed_chunks(runtime), estimator=estimator,
            token_budget=100, evaluation=evaluation, collect_telemetry=collect) for collect in (False, True)]
        assert results[0] == results[1]
        assert evaluation.evaluation_run_id is None

    asyncio.run(run())


def test_query_reuse_matches_normal_preparation(runtime):
    from omneum.context_selection import claim_id

    config, evaluator, observations, estimator = runtime
    client = OmneumClient(config, evaluator, local_persistence=None)

    async def run():
        evaluation = await client.evaluate_context(observations, estimator=estimator)
        chunks = computed_chunks(runtime)
        for chunk in chunks:
            chunk['source'] = next(observation.source for observation in observations
                if claim_id(observation.claim) in chunk['claim_ids'])
        options = dict(estimator=estimator, token_budget=100, strategy='coverage_support_density',
            user_query='Original', local_relevance='bm25', token_cost_exponent=1.0,
            complementary_evidence=True, include_dependencies=True)
        reused = await client.prepare_context(observations, chunks, evaluation=evaluation, **options)
        assert evaluator.context_calls == 1
        normal = await client.prepare_context(observations, chunks, **options)
        assert evaluator.context_calls == 2
        assert reused == normal

    asyncio.run(run())
