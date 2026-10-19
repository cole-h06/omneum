import asyncio
from copy import deepcopy
import json

import pytest

from omneum import open_stdio_client
from omneum.context_selection import token_count
from omneum.mcp import ClientSession
from benchmarks.context_evaluation.deployment import benchmark_deployment
from research.experiments.applied.agent_dataset.enterprise import agent_experiment as experiment
from research.experiments.applied.agent_dataset.enterprise.local_generator import LocalGenerator


def test_mcp_boundary_and_contexts(monkeypatch):
    observations, chunks = experiment.retrieve()
    chunks[0]['raw_text'] = ' \t' + chunks[0]['raw_text'] + '\r\n😀 '
    before = deepcopy(chunks)
    calls = []
    original = ClientSession.call_tool

    async def tracked(self, name, arguments=None, *args, **kwargs):
        calls.append((name, deepcopy(arguments)))
        return await original(self, name, arguments, *args, **kwargs)

    monkeypatch.setattr(ClientSession, 'call_tool', tracked)

    async def run():
        with benchmark_deployment() as (config, server):
            async with open_stdio_client(config, server, local_persistence=None) as client:
                for budget in (0, 160, 400, 2000):
                    arms, telemetry = await experiment.contexts(client, observations, chunks, budget, token_count)
                    selected = arms['omneum_selection'][0]
                    ranked = arms['omneum_ranked'][0]
                    assert {item['chunk_id'] for item in selected} == {item['chunk_id'] for item in ranked}
                    assert [item['chunk_id'] for item in selected] == [
                        item['chunk_id'] for item in chunks if item['chunk_id'] in {c['chunk_id'] for c in ranked}]
                    assert [item['score'] for item in ranked] == sorted([item['score'] for item in ranked], reverse=True)
                    by_id = {item['chunk_id']: item for item in chunks}
                    for chosen, _ in arms.values():
                        assert token_count(experiment.render(chosen)) <= budget
                        for item in chosen:
                            assert item['raw_text'].encode() == by_id[item['chunk_id']]['raw_text'].encode()
                    assert telemetry['evaluation']['source_reliability']
                    assert telemetry['evaluation']['claim_support']
                    assert telemetry['evaluation']['pairwise_dependencies']
                    if budget == 0:
                        assert all(not values[0] for values in arms.values())
                    if budget == 2000:
                        assert chunks[0]['raw_text'] in experiment.render(arms['baseline'][0])
                with pytest.raises(ValueError, match='budget'):
                    await experiment.contexts(client, observations, chunks, -1, token_count)

    asyncio.run(run())
    assert chunks == before
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
    result = experiment.execute(generator, task, chunks)
    context = experiment.render(chunks)
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
