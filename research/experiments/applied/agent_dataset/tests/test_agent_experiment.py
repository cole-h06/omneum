import asyncio
from copy import deepcopy
import json
import sqlite3
from types import SimpleNamespace

import pytest

from omneum import LocalPersistenceConfig, OmneumClient, open_stdio_client
from omneum.storage import SQLiteStorage
from research.adapters.observations import to_observations
from omneum.context_selection import token_count
from omneum.mcp import ClientSession
from benchmarks.context_selection.deployment import benchmark_deployment
from research.experiments.applied.agent_dataset.enterprise import agent_experiment as experiment
from research.experiments.applied.agent_dataset.enterprise.local_generator import LocalGenerator


@pytest.mark.parametrize("persist", [False, True])
def test_mcp_boundary_and_contexts(monkeypatch, tmp_path, persist):
    observations, chunks = experiment.retrieve()
    chunks[0]['raw_text'] = ' \t' + chunks[0]['raw_text'] + '\r\n😀 '
    before = deepcopy(chunks)
    calls = []
    original = ClientSession.call_tool
    prepare = OmneumClient.prepare_context
    preparations = []

    async def tracked_prepare(self, observations, raw_chunks, **kwargs):
        assert observations == to_observations(experiment.SOURCES, experiment.retrieve()[0])
        assert raw_chunks is chunks
        result = await prepare(self, observations, raw_chunks, **kwargs)
        preparations.append(result)
        return result

    monkeypatch.setattr(OmneumClient, 'prepare_context', tracked_prepare)

    async def tracked(self, name, arguments=None, *args, **kwargs):
        calls.append((name, deepcopy(arguments)))
        return await original(self, name, arguments, *args, **kwargs)

    monkeypatch.setattr(ClientSession, 'call_tool', tracked)

    storage = SQLiteStorage(tmp_path / 'context.sqlite3')
    persistence = LocalPersistenceConfig(storage) if persist else None

    async def run():
        with benchmark_deployment() as (config, server):
            async with open_stdio_client(config, server, local_persistence=persistence) as client:
                for budget in (0, 160, 400, 2000):
                    arms, telemetry = await experiment.contexts(client, observations, chunks, budget, token_count)
                    selected = arms['omneum_selection']['chunks']
                    ranked = arms['omneum_ranked']['chunks']
                    result = telemetry['sdk_result']
                    assert result is preparations[-1]
                    assert arms['omneum_ranked']['context'] is result['context']
                    assert ranked is result['chunks']
                    assert json.loads(json.dumps(result, allow_nan=False)) == result
                    assert set(result) == {'evaluation', 'selection', 'packed_chunk_ids', 'chunks', 'context'}
                    assert set(result['evaluation']) == {
                        'source_reliability', 'claim_support', 'max_claim_support', 'converged',
                        'iterations', 'convergence_delta', 'convergence_tolerance'}
                    support = result['evaluation']['claim_support']
                    assert result['evaluation']['max_claim_support'] == max(support.values())
                    assert result['evaluation']['converged']
                    assert len(result['evaluation']['source_reliability']) == 5
                    assert set(support) == {claim for item in chunks for claim in item['claim_ids']}
                    assert result['packed_chunk_ids'] == [item['chunk_id'] for item in ranked]
                    assert result['context'] == experiment.render(ranked)
                    input_tokens = token_count(experiment.render(chunks))
                    selected_tokens = token_count(result['context'])
                    covered_claims = {claim for chunk in chunks
                                      if chunk['chunk_id'] in result['packed_chunk_ids']
                                      for claim in chunk['claim_ids']}
                    assert result['selection'] == {
                        'input_tokens': input_tokens,
                        'selected_tokens': selected_tokens, 'token_budget': budget,
                        'reduction_ratio': (input_tokens - selected_tokens) / input_tokens,
                        'token_counter': 'custom',
                        'claim_coverage': {'covered': len(covered_claims), 'total': len(support)}}
                    for item in ranked:
                        claims = next(chunk['claim_ids'] for chunk in chunks if chunk['chunk_id'] == item['chunk_id'])
                        assert item['score'] == sum(support[claim] for claim in sorted(set(claims)))
                    # Model transport is stubbed here; preparation and MCP are real.
                    # Distinct prompts prove the original context is not consumed.
                    prompts = []
                    def generate(prompt):
                        prompts.append(prompt)
                        policy = {**experiment.GOLD, 'citations': result['packed_chunk_ids']}
                        return {'response': {'response': json.dumps({**policy, 'eligible': True})}}
                    execution = experiment.execute(SimpleNamespace(generate=generate), experiment.TASKS[0], result['context'])
                    assert execution['context'] is result['context']
                    assert all(prompt.split('Evidence:\n', 1)[1] == result['context'] for prompt in prompts)
                    assert execution['eligibility_tool'] == {'eligible': True}
                    if ranked:
                        assert experiment.evaluate(execution['answer'], experiment.TASKS[0], ranked, chunks)['measured']['task_success']
                    if budget == 400:
                        assert all(experiment.render(chunks) not in prompt for prompt in prompts)

                    assert {item['chunk_id'] for item in selected} == {item['chunk_id'] for item in ranked}
                    assert [item['chunk_id'] for item in selected] == [
                        item['chunk_id'] for item in chunks if item['chunk_id'] in {c['chunk_id'] for c in ranked}]
                    assert [item['score'] for item in ranked] == sorted([item['score'] for item in ranked], reverse=True)
                    by_id = {item['chunk_id']: item for item in chunks}
                    for prepared in arms.values():
                        assert token_count(prepared['context']) <= budget
                        for item in prepared['chunks']:
                            assert item['raw_text'].encode() == by_id[item['chunk_id']]['raw_text'].encode()
                    if budget == 0:
                        assert all(not values['chunks'] for values in arms.values())
                    if budget == 2000:
                        assert chunks[0]['raw_text'] in arms['baseline']['context']
                with pytest.raises(ValueError, match='budget'):
                    await experiment.contexts(client, observations, chunks, -1, token_count)

    asyncio.run(run())
    assert chunks == before
    assert len(preparations) == 4
    assert all(result['evaluation'] == preparations[0]['evaluation'] for result in preparations)
    if persist:
        with sqlite3.connect(storage.path) as db:
            for table, expected in {'evaluation_runs': 4, 'observations': 60,
                                    'source_scores': 20, 'claim_scores': 24,
                                    'source_dependencies': 40}.items():
                assert db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == expected
            assert db.execute('SELECT count(*) FROM observation_retrievals').fetchone()[0] == 60
            assert db.execute('SELECT count(*) FROM observation_parents WHERE parent_observation_id IS NOT NULL').fetchone()[0] == 12
    else:
        assert not storage.path.exists()
    wire = json.dumps(calls)
    assert all(chunk['raw_text'] not in wire and chunk['chunk_id'] not in wire for chunk in chunks)
    requests = [args for name, args in calls if name == 'evaluate_context']
    assert len(requests) == 4
    assert all(set(item) == {'source_id', 'attribute_id', 'claim_id'}
               for request in requests for item in request['assertions'])
    assert all(request == requests[0] for request in requests)


def test_llm_requests_and_outcomes():
    _, chunks = experiment.retrieve()
    chunks = chunks[:3]
    chunks[0]['raw_text'] += '\r\n \t😀 '
    policy = {**experiment.GOLD, 'citations': [chunks[0]['chunk_id']]}
    answer = {**policy, 'eligible': True}

    class Generator:
        def __init__(self):
            self.prompts = []

        def generate(self, prompt):
            self.prompts.append(prompt)
            return {'response': {'response': json.dumps(policy if len(self.prompts) == 1 else answer)}}

    generator = Generator()
    task = experiment.TASKS[1]
    context = experiment.render(chunks)
    result = experiment.execute(generator, task, context)
    assert generator.prompts == [experiment.POLICY_PROMPT.format(context=context),
                                 experiment.FINAL_PROMPT.format(days=20, policy=json.dumps(policy, sort_keys=True),
                                     tool=json.dumps({'eligible': True}, sort_keys=True), context=context)]
    assert result['context'] == context
    assert result['eligibility_tool'] == {'eligible': True}
    assert all(context in prompt for prompt in generator.prompts)
    assert experiment.evaluate(result['answer'], task, chunks, chunks)['measured']['task_success']
    assert not experiment.evaluate('{}', task, chunks, chunks)['measured']['task_success']
    assert not experiment.evaluate('invalid JSON', task, chunks, chunks)['measured']['task_success']
    assert experiment.eligibility({'return_window': 'unknown'}, 20) == {'eligible': None}
    assert experiment.parse_object('```json\n{"return_window": "30 days"}\n```') == {'return_window': '30 days'}
    answer['eligible'] = 1
    assert not experiment.evaluate(json.dumps(answer), task, chunks, chunks)['measured']['action_correct']


def test_generator_constructs_raw_request_and_checks_actual_usage():
    generator = LocalGenerator.__new__(LocalGenerator)
    generator.model = 'test'
    generator.endpoint = 'model'
    generator.tokenizer = 'tokenizer'
    generator.options = {'num_ctx': 100, 'num_predict': 10}
    calls = []
    usage = 3

    def request(endpoint, route, payload):
        calls.append((endpoint, route, payload))
        if route == '/apply-template':
            return {'prompt': '<user>original\r\n😀</user>'}
        if route == '/tokenize':
            return {'tokens': [1, 2, 3]}
        return {'response': '{}', 'prompt_eval_count': usage, 'eval_count': 2, 'done': True}

    generator.request = request
    result = generator.generate('original\r\n😀')
    assert calls[0] == ('tokenizer', '/apply-template', {'messages': [{'role': 'user', 'content': 'original\r\n😀'}]})
    assert result['request']['prompt'] == '<user>original\r\n😀</user>'
    assert result['request']['raw'] is True
    assert result['request']['options'] == generator.options
    usage = 4
    with pytest.raises(ValueError, match='Tokenizer mismatch'):
        generator.generate('original')
    generator.options['num_ctx'] = 12
    with pytest.raises(ValueError, match='context window'):
        generator.generate('original')
