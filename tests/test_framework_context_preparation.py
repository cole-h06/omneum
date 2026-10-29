import asyncio
import importlib
import json
import logging

import pytest

from examples.context_output import format_comparison, inspection_record, selection_summary
from examples.context_preparation import PreparationOptions
from examples.enterprise.workflow.run import QUESTION
from omneum import OmneumClient, reconstruct_context
from omneum.context_selection import token_count


FRAMEWORKS = ('langgraph', 'llamaindex', 'crewai', 'openai_agents', 'google_adk', 'microsoft')

MODULES = dict(zip(FRAMEWORKS, ('langgraph', 'llama_index.core', 'crewai', 'agents', 'google.adk', 'agent_framework'), strict=True))


@pytest.fixture
def framework(request):
    pytest.importorskip(MODULES[request.param])
    return request.param


async def execute(framework, options, *, routing=False, consumer=None, scenario="diversify_sources"):
    if framework == 'langgraph':
        if routing:
            from examples.langgraph.routing.graph import build_routing_graph
            from examples.langgraph.routing.scenarios import initial_observations
            graph = build_routing_graph(preloaded=True, model=consumer)
            inputs = dict(observations=initial_observations(scenario), retry_count=0)
        else:
            from examples.langgraph.graph import build_graph
            graph, inputs = build_graph(model=consumer), {}
        state = await graph.ainvoke(dict(question=QUESTION, observation_batches=[], preparation=options, **inputs))
        return state['generation'], state['answer']
    if framework == 'llamaindex':
        if routing:
            from examples.llamaindex.routing.workflow import RoutingWorkflow
            state = await RoutingWorkflow(timeout=60, preparation=options, chat_model=consumer).run(scenario=scenario)
            return state.generation, state.answer
        from examples.llamaindex.workflow import EnterpriseWorkflow
        handler = EnterpriseWorkflow(timeout=60, preparation=options, chat_model=consumer).run()
        answer = await handler
        return await handler.ctx.store.get('generation'), answer
    if framework == 'crewai':
        module = importlib.import_module('examples.crewai.routing.flow' if routing else 'examples.crewai.flow')
        cls = module.RoutingFlow if routing else module.EnterpriseFlow
        flow = cls(preparation=options, generation_agent=consumer, tracing=False, suppress_flow_events=True)
        await flow.kickoff_async(inputs={'scenario': scenario} if routing else {})
        return flow.state.generation, flow.state.answer
    if framework == 'microsoft' and routing:
        from examples.microsoft.routing.workflow import build_routing_workflow
        result = await build_routing_workflow(preparation=options, generation_agent=consumer).run(scenario)
        state = result.get_outputs()[0]
        return state.generation, state.answer
    module = importlib.import_module(f'examples.{framework}.routing.workflow' if routing else
                                     f'examples.{framework}.tools' if framework == 'microsoft' else f'examples.{framework}.agent')
    if routing:
        state = await module.run_routing(scenario, preparation=options, generation_agent=consumer)
        return state.generation, state.answer
    return await module.run_agent(preparation=options, generation_agent=consumer, inspect_context=consumer is None)


@pytest.mark.parametrize('framework', FRAMEWORKS, indirect=True)
@pytest.mark.parametrize('routing', (False, True))
@pytest.mark.parametrize('budget', (0, 200, 600))
def test_native_budget_comparison_and_logging(framework, routing, budget, example_daemon, monkeypatch, caplog):
    evaluations = []
    evaluate = OmneumClient._evaluate_context

    async def record_evaluate(self, *args, **kwargs):
        result = await evaluate(self, *args, **kwargs)
        evaluations.append(result)
        return result

    # The public alias is a separate descriptor; track both native entry points.
    monkeypatch.setattr(OmneumClient, '_evaluate_context', record_evaluate)
    monkeypatch.setattr(OmneumClient, 'evaluate_context', record_evaluate)
    caplog.set_level(logging.INFO, logger='omneum.execution')
    options = PreparationOptions(budget, compare=True, include_telemetry=True, collect_telemetry=True)
    generation, _ = asyncio.run(execute(framework, options, routing=routing))
    packet = generation['prepared_context']
    assert generation['evaluation'] in evaluations
    assert len(evaluations) == (2 if routing else 1)
    assert token_count(packet['context']) == packet['selection']['selected_tokens'] <= budget
    selected = packet['packed_chunk_ids']
    originals = {chunk['chunk_id']: chunk for chunk in generation['retrieved_chunks']}
    assert packet['context'] == '\n\n'.join(f'[{identifier}]\n{originals[identifier]["raw_text"]}' for identifier in selected)
    user_input = generation['messages'][1]['content']
    assert packet['context'] in user_input
    for identifier, chunk in originals.items():
        assert (chunk['raw_text'] in user_input) == (identifier in selected)
    if budget == 0:
        assert selected == packet['chunks'] == []
        assert packet['context'] == ''
    raw = reconstruct_context(generation['evaluation'], generation['retrieved_chunks'], strategy='retrieval', token_budget=budget)
    assert raw == generation['comparison']['raw_rag']
    assert raw['token_usage'] <= budget
    claims = {row['claim_id']: row for row in generation['structural_evaluation']}
    assert len(claims) == len(generation['evaluation'].claim_support)
    for item in generation['evaluation'].claim_support:
        from omneum.context_selection import claim_id
        row = claims[claim_id(item.claim)]
        assert row['supporting_source_count'] == item.supporting_source_count
        assert row['estimated_independent_support'] == item.estimated_independent_support_count
    assert selection_summary(generation)['rendering_order'] == selected
    comparison = format_comparison(generation)
    for label in ('Structural evaluation (all retrieved evidence)', '\nRaw RAG\n', '\nOmneum\n', 'Claim coverage:', 'Excluded:'):
        assert label in comparison
    assert 'latency' not in comparison
    report = inspection_record(generation, framework)
    assert json.loads(json.dumps(report, allow_nan=False)) == report
    assert 'context' not in report and 'messages' not in report and 'chunks' not in report
    assert 'raw_text' not in json.dumps(report)
    assert report['evaluation_run_id'] == generation['evaluation'].evaluation_run_id
    assert 'pairwise_dependencies' in report['evaluation']
    record, = [record for record in caplog.records if record.name == 'omneum.execution']
    assert record.evaluation_run_id == report['evaluation_run_id']
    assert report['telemetry']['cpu_time_scope'] == 'sdk_process_during_evaluation'
    assert report['telemetry']['peak_memory_scope'] == 'sdk_process_lifetime_peak_rss'


def model_consumer(framework, monkeypatch, requests):
    if framework == 'langgraph':
        from langchain_core.language_models.fake_chat_models import FakeListChatModel
        original = FakeListChatModel._agenerate

        async def generate(self, messages, *args, **kwargs):
            requests.append('\n'.join(message.content for message in messages))
            return await original(self, messages, *args, **kwargs)

        monkeypatch.setattr(FakeListChatModel, '_agenerate', generate)
        return FakeListChatModel(responses=['Test transport response.'])
    if framework == 'llamaindex':
        from llama_index.core.llms import ChatMessage, ChatResponse, MockLLM

        async def achat(self, messages, **kwargs):
            requests.append('\n'.join(message.content for message in messages))
            return ChatResponse(message=ChatMessage(role='assistant', content='Test transport response.'))

        monkeypatch.setattr(MockLLM, 'achat', achat)
        return MockLLM()
    if framework == 'crewai':
        from crewai import Agent, BaseLLM

        class TestLLM(BaseLLM):
            def call(self, messages, **kwargs):
                requests.append(messages if isinstance(messages, str) else '\n'.join(message['content'] for message in messages))
                return 'Final Answer: Test transport response.'

        return Agent(role='Policy analyst', goal='Answer from selected evidence', backstory='Policy reviewer',
                     llm=TestLLM(model='test'), allow_delegation=False, verbose=False)
    if framework == 'openai_agents':
        from agents import Agent, set_tracing_disabled
        from agents.items import ModelResponse
        from agents.models.openai_responses import OpenAIResponsesModel
        from agents.usage import Usage
        from openai.types.responses import ResponseOutputMessage, ResponseOutputText

        async def respond(self, *args, **kwargs):
            requests.append('\n'.join(item['content'] for item in kwargs['input']))
            return ModelResponse(output=[ResponseOutputMessage(id='test', type='message', role='assistant', status='completed',
                content=[ResponseOutputText(type='output_text', text='Test transport response.', annotations=[])])], usage=Usage(), response_id=None)

        set_tracing_disabled(True)
        monkeypatch.setenv('OPENAI_API_KEY', 'unused-test-key')
        monkeypatch.setattr(OpenAIResponsesModel, 'get_response', respond)
        return Agent(name='test', model='test')
    if framework == 'google_adk':
        from google.adk.agents import LlmAgent
        from google.adk.models.google_llm import Gemini
        from google.adk.models.llm_response import LlmResponse
        from google.genai import types

        async def respond(self, request, stream=False):
            requests.append('\n'.join(part.text for content in request.contents for part in content.parts or [] if part.text))
            yield LlmResponse(content=types.Content(role='model', parts=[types.Part(text='Test transport response.')]))

        monkeypatch.setattr(Gemini, 'generate_content_async', respond)
        return LlmAgent(name='test', model='gemini-2.5-flash', instruction='Answer from selected original passages.')
    from agent_framework import Agent, ChatResponse, Message
    from agent_framework.openai import OpenAIChatClient

    async def respond(self, *, messages, options, **kwargs):
        requests.append('\n'.join(message.text for message in messages))
        return ChatResponse(messages=Message('assistant', contents=['Test transport response.']))

    monkeypatch.setattr(OpenAIChatClient, '_inner_get_response', respond)
    return Agent(client=OpenAIChatClient(api_key='unused-test-key', model='test'))


@pytest.mark.parametrize('framework', FRAMEWORKS, indirect=True)
@pytest.mark.parametrize('scenario', (None, 'diversify_sources', 'retrieve_support', 'resolve_conflicts'))
def test_actual_native_model_transport(framework, scenario, example_daemon, monkeypatch):
    requests = []
    consumer = model_consumer(framework, monkeypatch, requests)
    generation, answer = asyncio.run(execute(framework, PreparationOptions(200), routing=scenario is not None, consumer=consumer,
        scenario=scenario or "diversify_sources"))
    assert 'Test transport response.' in answer
    request, = requests
    assert generation['prepared_context']['context'] in request
    for chunk in generation['retrieved_chunks']:
        assert (chunk['raw_text'] in request) == (chunk['chunk_id'] in generation['prepared_context']['packed_chunk_ids'])
    assert 'Omneum Evaluation' not in request
    assert 'estimated_independent_support' not in request


@pytest.mark.parametrize('framework', FRAMEWORKS, indirect=True)
@pytest.mark.parametrize('routing', (False, True))
def test_cli_single_redacted_json(framework, routing, example_daemon, monkeypatch, capsys):
    module = importlib.import_module(f'examples.{framework}.{"routing." if routing else ""}run')
    arguments = ['run', '--json', '--compare', '--token-budget', '0', '--include-telemetry']
    if routing:
        arguments += ['--scenario', 'all']
    monkeypatch.setattr('sys.argv', arguments)
    asyncio.run(module.main())
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    records = result['scenarios'] if routing else [result]
    assert len(records) == (3 if routing else 1)
    for record in records:
        assert record['selected_chunk_ids'] == record['rendering_order'] == []
        assert record['token_usage'] == record['token_budget'] == 0
        assert 'telemetry' in record
        assert 'raw_text' not in json.dumps(record)
    assert captured.err.count('Structural evaluation (all retrieved evidence)') == len(records)
    assert 'SDK duration:' not in captured.err


@pytest.mark.parametrize('framework', FRAMEWORKS, indirect=True)
def test_debug_json_toggle(framework, example_daemon, monkeypatch, capsys):
    module = importlib.import_module(f'examples.{framework}.run')
    monkeypatch.setattr(module, 'DEBUG_JSON', True)
    monkeypatch.setattr('sys.argv', ['run', '--token-budget', '0'])
    asyncio.run(module.main())
    assert json.loads(capsys.readouterr().out)['token_budget'] == 0


def test_cross_framework_context_parity_and_history(example_daemon, caplog):
    for module in MODULES.values():
        pytest.importorskip(module)
    import sqlite3
    from omneum.paths import get_context_db_path

    caplog.set_level(logging.INFO, logger='omneum.execution')

    async def run():
        packets = []
        for index, framework in enumerate(FRAMEWORKS, 1):
            generation, _ = await execute(framework, PreparationOptions(200))
            packets.append(generation['prepared_context'])
            assert 'telemetry' not in packets[-1]
            with sqlite3.connect(get_context_db_path()) as connection:
                assert connection.execute('SELECT count(*) FROM evaluation_runs').fetchone()[0] == index
                assert connection.execute('SELECT count(*) FROM execution_history').fetchone()[0] == index
                run_id = connection.execute('SELECT evaluation_run_id FROM execution_history ORDER BY rowid DESC LIMIT 1').fetchone()[0]
            assert run_id == generation['evaluation'].evaluation_run_id
        assert all(packet == packets[0] for packet in packets)
        logged, _ = await execute('langgraph', PreparationOptions(200, include_telemetry=True, collect_telemetry=True))
        telemetry = logged['prepared_context'].pop('telemetry')
        assert telemetry['sdk_end_to_end_latency_ms'] >= 0
        assert logged['prepared_context'] == packets[0]

    asyncio.run(run())
    assert len([record for record in caplog.records if record.name == 'omneum.execution']) == 1


@pytest.mark.parametrize('framework', FRAMEWORKS, indirect=True)
@pytest.mark.parametrize('style', ('json', 'human'))
def test_cli_logging_file_and_explicit_context(framework, style, example_daemon, tmp_path, monkeypatch, capsys):
    module = importlib.import_module(f'examples.{framework}.run')
    path = tmp_path / 'execution.log'
    monkeypatch.setattr('sys.argv', ['run', '--json', '--include-context', '--collect-telemetry',
        '--telemetry-format', style, '--telemetry-log-file', str(path), '--token-budget', '200'])
    asyncio.run(module.main())
    captured = capsys.readouterr()
    record = json.loads(captured.out)
    assert record['context'] in record['messages'][1]['content']
    assert 'telemetry' not in record
    logged = path.read_text()
    assert 'raw_text' not in logged and record['context'] not in logged
    if style == 'json':
        execution = json.loads(logged)
        assert execution['evaluation_run_id'] == record['evaluation_run_id']
        assert execution['execution']['selected_tokens'] == record['token_usage']
    else:
        assert 'SDK duration:' in logged
        assert 'Peak SDK RSS:' in logged
        assert 'sdk_process_during_evaluation' in logged


@pytest.mark.parametrize('budget', (-1, True, 1.0, '200'))
def test_invalid_framework_budget(budget):
    with pytest.raises(ValueError, match='nonnegative integer'):
        PreparationOptions(token_budget=budget)


@pytest.mark.parametrize('framework', FRAMEWORKS, indirect=True)
@pytest.mark.parametrize('routing', (False, True))
def test_executable_entry_points(framework, routing, example_daemon, tmp_path):
    import os
    import subprocess
    import sys

    module = f'examples.{framework}.{"routing." if routing else ""}run'
    bootstrap = (
        'import sys,runpy; from pathlib import Path; import omneum.paths; '
        'database=Path(sys.argv.pop(1)); module=sys.argv.pop(1); '
        'omneum.paths.get_context_db_path=lambda: database; sys.argv[0]=module; '
        'runpy.run_module(module,run_name="__main__")'
    )
    arguments = [sys.executable, '-c', bootstrap, str(tmp_path / 'subprocess' / 'omneum.db'), module,
                 '--json', '--compare', '--include-telemetry', '--collect-telemetry', '--token-budget', '600']
    if routing:
        arguments += ['--scenario', 'all']
    environment = {key: value for key, value in os.environ.items() if key not in (
        'OPENAI_API_KEY', 'GOOGLE_API_KEY', 'GEMINI_API_KEY', 'GOOGLE_APPLICATION_CREDENTIALS')}
    result = subprocess.run(arguments, env=environment, text=True, capture_output=True, timeout=90)
    assert result.returncode == 0, result.stderr
    document = json.loads(result.stdout)
    records = document['scenarios'] if routing else [document]
    assert len(records) == (3 if routing else 1)
    assert result.stderr.count('Structural evaluation (all retrieved evidence)') == len(records)
    executions = [json.loads(line) for line in result.stderr.splitlines() if line.startswith('{"event": "omneum.execution"')]
    assert len(executions) == len(records)
    for record, execution in zip(records, executions, strict=True):
        assert record['evaluation_run_id'] == execution['evaluation_run_id']
        assert record['token_usage'] <= 600
    print(f'{module}: exit=0; {len(records)} scenario(s); valid JSON; {len(executions)} execution record(s)')


def test_adk_routing_rejects_missing_model_response(example_daemon, monkeypatch):
    pytest.importorskip("google.adk")
    from google.adk.agents import LlmAgent
    from google.adk.models.google_llm import Gemini
    from examples.google_adk.routing.workflow import run_routing

    async def respond(self, request, stream=False):
        for response in ():
            yield response

    monkeypatch.setattr(Gemini, 'generate_content_async', respond)
    with pytest.raises(RuntimeError, match='no final text response'):
        asyncio.run(run_routing('diversify_sources', generation_agent=LlmAgent(name='test', model='gemini-2.5-flash')))
