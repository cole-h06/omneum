import asyncio
from copy import deepcopy
import json

import pytest
from omneum.mcp import ClientSession

from examples.enterprise.agents.api import api_agent
from examples.enterprise.agents.common import (
    BRIEF_SOURCE,
    GATEWAY_SOURCE,
    POLICY_SOURCE,
    REGISTRY_SOURCE,
    RUNBOOK_SOURCE,
    VENDOR_SOURCE,
)
from examples.enterprise.agents.documents import documents_agent
from examples.enterprise.agents.research import research_agent
from examples.enterprise.agents.search import search_agent
from examples.enterprise.agents.sql import sql_agent
from examples.enterprise.config import example_deployment
from examples.enterprise.workflow.run import (
    QUESTION,
    RETRIEVAL_AGENTS,
    SOURCE_LABELS,
    collect_observations,
    estimator_config,
    prepare_workflow,
    run_workflow,
)
from examples.enterprise.workflow.generate import generation_messages
from examples.enterprise.workflow.retrieval import (
    DATA,
    SOURCE_FILES,
    collect_chunks,
    validate_chunks,
)
from omneum import evaluate_context, reconstruct_context
from omneum.context_selection import claim_id, token_count
from omneum.dependency import estimate_dependencies
SOURCES = {
    "policy": POLICY_SOURCE,
    "runbook": RUNBOOK_SOURCE,
    "brief": BRIEF_SOURCE,
    "registry": REGISTRY_SOURCE,
    "gateway": GATEWAY_SOURCE,
    "vendor": VENDOR_SOURCE,
}


def test_observations():
    values = collect_observations()

    assert RETRIEVAL_AGENTS == (
        documents_agent,
        research_agent,
        sql_agent,
        api_agent,
        search_agent,
    )
    assert tuple(len(agent()) for agent in RETRIEVAL_AGENTS) == (6, 3, 3, 3, 2)
    assert len(values) == 17
    assert len({value.source for value in values}) == 6
    assert {value.claim.attribute for value in values} == {
        "input_data_policy",
        "provider_retention",
        "processing_region",
    }
    assert {value.claim.value for value in values} == {
        "redacted customer content only",
        "unredacted customer content allowed",
        "0 days",
        "30 days",
        "EU",
        "US",
    }
    assert all(value.observed_at is not None for value in values)
    assert all(value.source_modified_at is not None for value in values)
    assert all(value.upstream_sources is not None for value in values)
    assert all(value.cited_sources is not None for value in values)
    assert all(value.parent_observation_ids is not None for value in values)

    by_id = {value.observation_id: value for value in values}
    for suffix in ("input-data", "retention", "region"):
        brief = by_id[f"brief-{suffix}"]
        registry = by_id[f"registry-{suffix}"]
        gateway = by_id[f"gateway-{suffix}"]
        assert brief.parent_observation_ids == (f"runbook-{suffix}",)
        assert registry.parent_observation_ids == (f"policy-{suffix}",)
        assert gateway.parent_observation_ids == (f"registry-{suffix}",)


def test_dependencies():
    values = collect_observations()
    pairs, clusters = estimate_dependencies(
        tuple(SOURCES.values()),
        values,
        estimator_config(),
    )
    names = {
        (source.kind, source.identifier): name
        for name, source in SOURCES.items()
    }
    dependencies = {
        frozenset((
            names[(pair.source_a.kind, pair.source_a.identifier)],
            names[(pair.source_b.kind, pair.source_b.identifier)],
        )): pair.dependency
        for pair in pairs
    }

    assert len(pairs) == 15
    assert dependencies[frozenset(("runbook", "brief"))] == pytest.approx(
        1.0
    )
    assert dependencies[frozenset(("policy", "registry"))] == pytest.approx(
        1.0
    )
    assert dependencies[frozenset(("registry", "gateway"))] == pytest.approx(
        1.0
    )
    assert dependencies[frozenset(("vendor", "gateway"))] == pytest.approx(
        0.0
    )
    assert {
        frozenset(
            names[(source.kind, source.identifier)]
            for source in cluster.sources
        )
        for cluster in clusters
    } == {
        frozenset(("policy", "registry", "gateway")),
        frozenset(("runbook", "brief")),
        frozenset(("vendor",)),
    }


def test_stdio_workflow(monkeypatch, example_daemon):
    calls = []
    original_call_tool = ClientSession.call_tool

    async def tracked_call_tool(self, name, arguments=None, *args, **kwargs):
        calls.append((id(self), name, json.loads(json.dumps(arguments))))
        return await original_call_tool(
            self,
            name,
            arguments,
            *args,
            **kwargs,
        )

    monkeypatch.setattr(ClientSession, "call_tool", tracked_call_tool)

    async def run():
        with example_deployment() as (config, server):
            first = await run_workflow(config, server)
        second = await run_workflow()
        return first, second

    (first, first_output), (second, second_output) = asyncio.run(run())

    assert first == second
    assert first_output == second_output
    assert len(first.source_reliability) == 6
    assert len(first.claim_support) == 6
    assert len(first.pairwise_dependencies) == 15
    assert QUESTION in first_output
    assert "Retrieved context:" in first_output
    assert "Source references:" in first_output
    assert "Reliability:" not in first_output
    assert "Application decision:" not in first_output
    assert "Omneum Evaluation" not in first_output

    sessions = {session for session, _, _ in calls}
    assert len(sessions) == 2
    for session in sessions:
        session_calls = [item for item in calls if item[0] == session]
        assert sum(name == "evaluate_voprf" for _, name, _ in session_calls) == 15
        assert sum(name == "evaluate_context" for _, name, _ in session_calls) == 1

    assertion_requests = [
        arguments
        for _, name, arguments in calls
        if name == "evaluate_context"
    ]
    observations = collect_observations()
    private_values = {
        value.observation_id
        for value in observations
    } | {
        value.source.identifier
        for value in observations
    } | {
        value.source.owner_id
        for value in observations
    } | {
        value.source_modified_at.isoformat()
        for value in observations
    } | {
        value.claim.entity
        for value in observations
    } | {
        value.claim.attribute
        for value in observations
    } | {
        value.claim.value
        for value in observations
    } | set(SOURCE_LABELS.values()) | {
        chunk["raw_text"] for chunk in collect_chunks(observations)
    }
    for request in assertion_requests:
        encoded = json.dumps(request)
        assert set(request) == {
            "protocol_version",
            "deployment_id",
            "voprf_key_version",
            "voprf_mode",
            "voprf_ciphersuite",
            "linkage_encoding_version",
            "assertions",
            "source_pairs",
        }
        assert len(request["assertions"]) == 17
        assert len(request["source_pairs"]) == 15
        stack = [request]
        wire_strings = set()
        while stack:
            value = stack.pop()
            if type(value) is dict:
                stack.extend(value.values())
            elif type(value) is list:
                stack.extend(value)
            elif type(value) is str:
                wire_strings.add(value)
        assert private_values.isdisjoint(wire_strings)
        assert "Application conclusion" not in encoded


def test_retrieved_chunk_mapping():
    observations = collect_observations()
    chunks = collect_chunks(observations)
    by_id = {item.observation_id: item for item in observations}

    assert len(chunks) == 6
    assert sum(len(chunk["observation_ids"]) for chunk in chunks) == 17
    for chunk, (source, filename) in zip(chunks, SOURCE_FILES, strict=True):
        assert chunk["raw_text"] == (DATA / filename).read_text(encoding="utf-8")
        assert chunk["source"] == source
        assert len(chunk["claim_ids"]) > 1
        assert set(chunk["claim_ids"]) == {
            claim_id(by_id[identifier].claim) for identifier in chunk["observation_ids"]
        }
        assert all(by_id[identifier].source == source for identifier in chunk["observation_ids"])

    # An observation may also support a second passage from the same source.
    duplicate_passage = {**chunks[0], "chunk_id": "policy-second-passage"}
    validate_chunks(observations, [*chunks, duplicate_passage])


@pytest.mark.parametrize("defect", [
    "missing_chunk", "missing_claim", "unknown_claim", "duplicate_chunk",
    "unknown_observation", "duplicate_observation", "missing_observation",
    "wrong_source", "wrong_claim", "duplicate_input_observation",
    "missing_observation_ids", "missing_source", "empty_observation_id",
])
def test_invalid_chunk_relationships(defect):
    observations = collect_observations()
    chunks = deepcopy(collect_chunks(observations))
    if defect == "missing_chunk":
        chunks.pop(0)
    elif defect == "missing_claim":
        del chunks[0]["claim_ids"]
    elif defect == "unknown_claim":
        chunks[0]["claim_ids"] = ["unknown"]
    elif defect == "duplicate_chunk":
        chunks.append(chunks[0])
    elif defect == "unknown_observation":
        chunks[0]["observation_ids"] = ["unknown"]
    elif defect == "duplicate_observation":
        chunks[0]["observation_ids"].append(chunks[0]["observation_ids"][0])
    elif defect == "missing_observation":
        chunks[0]["observation_ids"] = []
    elif defect == "wrong_source":
        chunks[0]["source"] = VENDOR_SOURCE
    elif defect == "wrong_claim":
        chunks[0]["claim_ids"] = chunks[1]["claim_ids"]
    elif defect == "duplicate_input_observation":
        observations = (*observations, observations[0])
    elif defect == "missing_observation_ids":
        del chunks[0]["observation_ids"]
    elif defect == "missing_source":
        del chunks[0]["source"]
    elif defect == "empty_observation_id":
        chunks[0]["observation_ids"] = [""]
    with pytest.raises(ValueError):
        validate_chunks(observations, chunks)


@pytest.mark.parametrize("budget", [0, 200, 600])
def test_reconstruction_and_generation(budget, example_daemon):
    observations = collect_observations()
    chunks = collect_chunks(observations)
    result = asyncio.run(prepare_workflow(token_budget=budget))
    prepared = result["prepared_context"]
    repeated = asyncio.run(prepare_workflow(token_budget=budget))

    assert prepared == repeated["prepared_context"]
    assert prepared["selection"]["selected_tokens"] == token_count(prepared["context"]) <= budget
    selected = [
        next(chunk for chunk in chunks if chunk["chunk_id"] == identifier)
        for identifier in prepared["packed_chunk_ids"]
    ]
    assert prepared["context"] == "\n\n".join(
        f"[{chunk['chunk_id']}]\n{chunk['raw_text']}" for chunk in selected
    )
    messages = generation_messages(QUESTION, prepared["context"], selected)
    assert messages == result["messages"]
    assert QUESTION in messages[1]["content"]
    assert prepared["context"] in messages[1]["content"]
    for chunk in chunks:
        if chunk in selected:
            assert chunk["raw_text"] in messages[1]["content"]
            assert chunk["source"].identifier in messages[1]["content"]
        else:
            assert chunk["raw_text"] not in messages[1]["content"]
            assert chunk["chunk_id"] not in messages[1]["content"]
    assert "Reliability:" not in messages[1]["content"]
    assert "Application decision:" not in messages[1]["content"]
    json.dumps(messages, allow_nan=False)
    if budget == 0:
        assert prepared["context"] == ""
        assert prepared["packed_chunk_ids"] == []


def test_prepared_stdio_workflow(example_daemon):
    result = asyncio.run(prepare_workflow())
    evaluation = result["evaluation"]
    prepared = result["prepared_context"]
    expected = evaluate_context(collect_observations(), estimator=estimator_config())

    assert {item.source: item.reliability for item in evaluation.source_reliability} == pytest.approx({
        item.source: item.reliability for item in expected.source_reliability
    })
    assert {claim_id(item.claim): item.support for item in evaluation.claim_support} == pytest.approx({
        claim_id(item.claim): item.support for item in expected.claim_support
    })
    assert evaluation.pairwise_dependencies == expected.pairwise_dependencies
    assert len(evaluation.claim_support) == 6
    assert all(item.conflicting_claims for item in evaluation.claim_support)
    assert len(evaluation.pairwise_dependencies) == 15
    assert prepared["selection"]["input_tokens"] == 893
    # This is SDK/core parity for the explicitly configured query/complementary
    # path, not a frozen benchmark context. Its old token snapshot predates
    # converged-source attribution and final query weighting.
    diagnostics = result["query_diagnostics"]
    eligible = set(diagnostics["eligible_chunk_ids"])
    chunks = [c for c in collect_chunks(collect_observations()) if c["chunk_id"] in eligible]
    direct = reconstruct_context(expected, chunks, token_budget=600,
        strategy="coverage_support_density", complementary_evidence=True,
        token_cost_exponent=1.0, count_tokens=token_count,
        chunk_relevance=diagnostics["normalized_relevance_scores"], _allow_unmapped_claims=True)
    assert prepared["context"] == direct["context"]
    assert prepared["packed_chunk_ids"] == direct["selected_chunk_ids"]
    assert prepared["selection"]["selected_tokens"] == token_count(prepared["context"]) == direct["token_usage"]
    assert prepared["selection"]["claim_coverage"] == direct["claim_coverage"]
    assert prepared["selection"]["token_counter"] == "unicode_word_punctuation_proxy"
    assert result["query_diagnostics"]["relevance_source"] == "bm25"
    assert result["query_diagnostics"]["evaluation_scope"] == "full"
    assert "pairwise_dependencies" in prepared["evaluation"]
    assert set(prepared) == {"context", "chunks", "packed_chunk_ids", "selection", "evaluation"}
    assert prepared["context"] in result["messages"][1]["content"]
    assert evaluation.evaluation_latency_ms >= 0


def test_sdk_preparation_contract(example_daemon, monkeypatch):
    from examples.context_preparation import PreparationOptions
    from omneum import OmneumClient

    calls = []
    original = OmneumClient.prepare_context

    async def prepare(self, observations, chunks, **options):
        calls.append((observations, chunks, options))
        return await original(self, observations, chunks, **options)

    monkeypatch.setattr(OmneumClient, 'prepare_context', prepare)
    result = asyncio.run(prepare_workflow(preparation=PreparationOptions(200)))
    observations, chunks, options = calls.pop()
    assert not calls
    assert observations == collect_observations()
    assert chunks == collect_chunks(observations)
    assert options['user_query'] == QUESTION
    assert options['token_budget'] == 200
    assert options['local_relevance'] == 'bm25'
    assert options['strategy'] == 'coverage_support_density'
    assert options['token_cost_exponent'] == 1.0
    assert options['complementary_evidence'] is True
    assert options['include_dependencies'] is True
    assert options['query_evaluation'] == 'full'
    assert options['evaluation'] is result['evaluation']
    assert result['configuration']['token_budget'] == 200


@pytest.mark.parametrize('budget', [0, 200, 600])
def test_raw_rag_comparison(budget, example_daemon):
    from examples.context_output import format_comparison, selection_summary
    from examples.context_preparation import PreparationOptions

    result = asyncio.run(prepare_workflow(preparation=PreparationOptions(budget, compare=True)))
    chunks = collect_chunks(collect_observations())
    assert result['retrieved_chunks'] == chunks
    raw = result['comparison']['raw_rag']
    assert raw == reconstruct_context(result['evaluation'], chunks, token_budget=budget, strategy='retrieval')
    assert raw['token_budget'] == result['prepared_context']['selection']['token_budget'] == budget
    assert raw['token_usage'] == token_count(raw['context']) <= budget
    for chunk in chunks:
        assert (chunk['raw_text'] in raw['context']) == (chunk['chunk_id'] in raw['selected_chunk_ids'])
    structural = {row['claim_id']: row for row in result['structural_evaluation']}
    assert len(structural) == len(result['evaluation'].claim_support) == 6
    for claim in result['evaluation'].claim_support:
        row = structural[claim_id(claim.claim)]
        assert row['supporting_source_count'] == claim.supporting_source_count
        assert row['estimated_independent_support'] == claim.estimated_independent_support_count
    for selection in (selection_summary(result), selection_summary(result, raw)):
        assert selection['rendering_order'] == selection['selected_chunk_ids']
        assert set(selection['excluded_chunk_ids']).isdisjoint(selection['selected_chunk_ids'])
        assert set(selection['excluded_chunk_ids']) | set(selection['selected_chunk_ids']) == {chunk['chunk_id'] for chunk in chunks}
    formatted = format_comparison(result)
    assert formatted.startswith('Structural evaluation (all retrieved evidence)\n')
    assert '\nRaw RAG\n' in formatted and '\nOmneum\n' in formatted
    assert 'Claim coverage:' in formatted and 'Excluded:' in formatted
    assert 'SDK duration:' not in formatted


@pytest.mark.parametrize('include', [False, True])
@pytest.mark.parametrize('collect', [False, True])
def test_execution_telemetry_and_history(include, collect, example_daemon, caplog):
    import logging
    import sqlite3
    from examples.context_preparation import PreparationOptions
    from omneum.metrics import JsonExecutionFormatter
    from omneum.paths import get_context_db_path

    caplog.set_level(logging.INFO, logger='omneum.execution')
    result = asyncio.run(prepare_workflow(preparation=PreparationOptions(
        include_telemetry=include, collect_telemetry=collect,
    )))
    packet = result['prepared_context']
    assert ('telemetry' in packet) is include
    records = [record for record in caplog.records if record.name == 'omneum.execution']
    assert len(records) == int(collect)
    with sqlite3.connect(get_context_db_path()) as connection:
        connection.row_factory = sqlite3.Row
        assert connection.execute('SELECT count(*) FROM evaluation_runs').fetchone()[0] == 1
        assert connection.execute('SELECT count(*) FROM execution_history').fetchone()[0] == 1
        row = dict(connection.execute('SELECT * FROM execution_history').fetchone())
    assert row['evaluation_run_id'] == result['evaluation'].evaluation_run_id
    for key in ('input_tokens', 'selected_tokens', 'token_budget', 'reduction_ratio'):
        assert row[key] == packet['selection'][key]
    if include:
        for key, value in packet['telemetry'].items():
            assert value == row[key]
        for key in ('sdk_end_to_end_latency_ms', 'graph_evaluation_latency_ms', 'mcp_roundtrip_latency_ms',
                    'chunk_selection_latency_ms', 'context_reconstruction_latency_ms', 'cpu_time_ms'):
            value = packet['telemetry'][key]
            assert value is None or value >= 0
        assert packet['telemetry']['cpu_time_scope'] == 'sdk_process_during_evaluation'
        assert packet['telemetry']['peak_memory_scope'] == 'sdk_process_lifetime_peak_rss'
    if collect:
        logged = json.loads(JsonExecutionFormatter().format(records[0]))
        assert logged['event'] == 'omneum.execution'
        assert logged['evaluation_run_id'] == row['evaluation_run_id']
        assert logged['execution']['selected_tokens'] == row['selected_tokens']
        assert all(chunk['raw_text'] not in json.dumps(logged) for chunk in result['retrieved_chunks'])
    json.dumps(packet, allow_nan=False)


def test_unavailable_telemetry_is_not_substituted(example_daemon, monkeypatch):
    from examples.context_preparation import PreparationOptions
    monkeypatch.setattr('omneum.client._peak_process_memory_bytes', lambda: None)
    result = asyncio.run(prepare_workflow(preparation=PreparationOptions(include_telemetry=True)))
    assert result['prepared_context']['telemetry']['peak_memory_bytes'] is None


@pytest.mark.parametrize('arguments', [
    [], ['--inspect-context'], ['--compare'], ['--json'],
    ['--json', '--include-context'], ['--json', '--include-telemetry'],
    ['--json', '--compare', '--token-budget', '0'],
    ['--json', '--collect-telemetry'],
    ['--json', '--collect-telemetry', '--telemetry-format', 'human'],
])
def test_enterprise_cli(arguments, example_daemon, monkeypatch, capsys):
    from examples.context_output import format_comparison, inspection_record
    from examples.enterprise.workflow import run

    captured_results = []
    original = run.prepare_workflow

    async def capture(*args, **kwargs):
        result = await original(*args, **kwargs)
        captured_results.append(result)
        return result

    monkeypatch.setattr(run, 'prepare_workflow', capture)
    monkeypatch.setattr('sys.argv', ['run', *arguments])
    run.main()
    captured = capsys.readouterr()
    result, = captured_results
    if '--json' in arguments:
        document = json.loads(captured.out)
        assert document == inspection_record(result, 'enterprise', include_context='--include-context' in arguments)
        assert document['rendering_order'] == result['prepared_context']['packed_chunk_ids']
        assert ('messages' in document) is ('--include-context' in arguments)
        if '--include-context' in arguments:
            assert document['messages'] == result['messages']
        else:
            assert 'raw_text' not in captured.out
            assert all(chunk['raw_text'] not in captured.out for chunk in result['retrieved_chunks'])
    elif '--compare' in arguments:
        assert captured.out == ''
    else:
        assert captured.out == result['messages'][1]['content'] + '\n'
    if '--compare' in arguments:
        assert format_comparison(result) + '\n' in captured.err
    else:
        assert 'Structural evaluation (all retrieved evidence)' not in captured.err
    if '--collect-telemetry' in arguments:
        if 'human' in arguments:
            assert 'SDK duration:' in captured.err and 'Peak SDK RSS:' in captured.err
        else:
            logs = [json.loads(line) for line in captured.err.splitlines() if line.startswith('{"event":')]
            assert len(logs) == 1
    else:
        assert 'omneum.execution' not in captured.err


@pytest.mark.parametrize('style', ['json', 'human'])
def test_cli_telemetry_file(style, example_daemon, tmp_path, monkeypatch, capsys):
    from examples.enterprise.workflow import run

    destination = tmp_path / 'execution.log'
    monkeypatch.setattr('sys.argv', ['run', '--json', '--collect-telemetry', '--telemetry-format', style,
        '--telemetry-log-file', str(destination)])
    run.main()
    captured = capsys.readouterr()
    record = json.loads(captured.out)
    assert 'telemetry' not in record
    assert 'omneum.execution' not in captured.err
    output = destination.read_text()
    if style == 'json':
        execution = json.loads(output)
        assert execution['evaluation_run_id'] == record['evaluation_run_id']
    else:
        assert 'SDK duration:' in output and 'Peak SDK RSS:' in output


@pytest.mark.parametrize('budget', [-1, True, 1.5])
def test_invalid_workflow_budget(budget, example_daemon):
    with pytest.raises(ValueError, match='nonnegative integer'):
        asyncio.run(prepare_workflow(token_budget=budget))


def test_partial_deployment_is_rejected():
    from examples.context_preparation import prepare_generation

    for config, server in ((object(), None), (None, object())):
        with pytest.raises(TypeError, match='supplied together'):
            asyncio.run(prepare_workflow(config, server))
        with pytest.raises(TypeError, match='supplied together'):
            asyncio.run(prepare_generation(collect_observations(), question=QUESTION,
                estimator=estimator_config(), config=config, server=server))


def test_enterprise_entry_point(example_daemon, tmp_path):
    import os
    import subprocess
    import sys

    bootstrap = (
        'import sys,runpy; from pathlib import Path; import omneum.paths; '
        'database=Path(sys.argv.pop(1)); omneum.paths.get_context_db_path=lambda: database; '
        'sys.argv[0]="examples.enterprise.workflow.run"; '
        'runpy.run_module("examples.enterprise.workflow.run",run_name="__main__")'
    )
    environment = {key: value for key, value in os.environ.items()
                   if key not in ('OPENAI_API_KEY', 'GOOGLE_API_KEY', 'GEMINI_API_KEY')}
    result = subprocess.run([sys.executable, '-c', bootstrap, str(tmp_path / 'entry-point' / 'omneum.db'),
        '--json', '--compare', '--include-context', '--include-telemetry', '--token-budget', '200'],
        env=environment, text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr
    record = json.loads(result.stdout)
    assert record['framework'] == 'enterprise'
    assert record['token_budget'] == 200 and record['token_usage'] <= 200
    assert record['context'] in record['messages'][1]['content']
    assert record['rendering_order'] == record['selected_chunk_ids']
    assert 'telemetry' in record
    assert 'Structural evaluation (all retrieved evidence)' in result.stderr
    assert '\nRaw RAG\n' in result.stderr and '\nOmneum\n' in result.stderr


def test_debug_json_toggle(example_daemon, monkeypatch, capsys):
    from examples.enterprise.workflow import run
    monkeypatch.setattr(run, 'DEBUG_JSON', True)
    monkeypatch.setattr('sys.argv', ['run', '--token-budget', '0'])
    run.main()
    record = json.loads(capsys.readouterr().out)
    assert record['selected_chunk_ids'] == []
    assert record['token_budget'] == record['token_usage'] == 0
