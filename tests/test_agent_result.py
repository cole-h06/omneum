import asyncio
from copy import deepcopy
import json
import logging
import math
import sys
from time import perf_counter, process_time

import pytest

from omneum import LocalPersistenceConfig, OmneumClient, SQLiteStorage, evaluate, reconstruct_context
from omneum.agent_result import _serialize_context_result as serialize_context_result
from omneum.canonicalization import canonicalize_source
from omneum.context_selection import claim_id
from omneum.metrics import _execution_telemetry, _peak_process_memory_bytes
from omneum.serialization import serialize_source
from test_local_persistence import runtime
from test_storage_evaluation import computed


def mapped_chunks(evaluation):
    return [dict(chunk_id=f"local-{index}", raw_text=f" \tOriginal {index}\r\n😀 ", claim_ids=[claim_id(item.claim)])
            for index, item in enumerate(evaluation.claim_support)]


def result_fixture():
    evaluation = evaluate([dict(url="https://a.example", value="yes"), dict(url="https://b.example", value="no")])
    return dict(evaluation=evaluation, **reconstruct_context(evaluation, mapped_chunks(evaluation), token_budget=100))


def test_json_contract_and_original_scores():
    result = result_fixture()
    before = deepcopy(result)
    payload = serialize_context_result(result)
    assert set(payload) == {"evaluation", "selection", "packed_chunk_ids", "chunks", "context"}
    assert set(payload["evaluation"]) == {"source_reliability", "claim_support", "max_claim_support",
        "converged", "iterations", "convergence_delta", "convergence_tolerance"}
    assert set(payload["selection"]) == {"input_tokens", "selected_tokens", "token_budget", "reduction_ratio", "token_counter", "claim_coverage"}
    assert payload["selection"]["claim_coverage"] == result["claim_coverage"]
    assert payload["selection"]["claim_coverage"] is not result["claim_coverage"]
    assert "telemetry" not in payload
    assert json.loads(json.dumps(payload, allow_nan=False)) == payload
    assert result == before
    assert payload["chunks"] == result["chunks"]
    assert payload["context"] == result["context"]
    assert payload["packed_chunk_ids"] == result["selected_chunk_ids"]
    expected_sources = {}
    for item in result["evaluation"].source_reliability:
        source = item.source
        key = serialize_source(source.kind, canonicalize_source(source.kind, source.identifier)).hex()
        expected_sources[key] = item.reliability
    assert payload["evaluation"]["source_reliability"] == expected_sources
    supports = {claim_id(item.claim): item.support for item in result["evaluation"].claim_support}
    assert payload["evaluation"]["claim_support"] == supports
    assert payload["evaluation"]["max_claim_support"] == max(supports.values())
    assert "latency_ms" not in payload["evaluation"]
    assert payload["evaluation"]["converged"] is True
    assert type(payload["evaluation"]["iterations"]) is int
    assert payload["selection"]["reduction_ratio"] == (result["candidate_input_tokens"]-result["token_usage"])/result["candidate_input_tokens"]
    assert payload["selection"]["token_counter"] == "unspecified"
    payload["chunks"][0]["raw_text"] = "changed copy"
    assert result["chunks"] == before["chunks"]


def test_empty_chunks_zero_budget_and_nonadditive_zero_input():
    evaluation = result_fixture()["evaluation"]
    for chunks, budget in (([], 0), (mapped_chunks(evaluation), 0)):
        result = dict(evaluation=evaluation, **reconstruct_context(evaluation, chunks, token_budget=budget))
        payload = serialize_context_result(result)
        assert payload["packed_chunk_ids"] == payload["chunks"] == []
        assert payload["context"] == ""
        assert payload["selection"]["selected_tokens"] == 0
        assert payload["selection"]["claim_coverage"] == {"covered": 0, "total": 2}
        assert payload["selection"]["reduction_ratio"] == (0.0 if not chunks else 1.0)
    evaluation = evaluate([dict(url="https://a.example", value="yes")])
    chunks = mapped_chunks(evaluation)
    chunks.append({**chunks[0], "chunk_id": "local-1"})
    def counter(text):
        return 0 if "local-0" in text and "local-1" in text else int(bool(text))
    result = dict(evaluation=evaluation, **reconstruct_context(evaluation, chunks, token_budget=1, count_tokens=counter))
    assert result["candidate_input_tokens"] == 0 and result["token_usage"] == 1
    assert serialize_context_result(result)["selection"]["reduction_ratio"] is None
    with pytest.raises(TypeError):
        serialize_context_result({})


@pytest.mark.parametrize("field,value", [("token_budget", -1), ("token_usage", True), ("candidate_input_tokens", 1.5)])
def test_invalid_token_metadata(field, value):
    result = result_fixture()
    result[field] = value
    with pytest.raises(ValueError):
        serialize_context_result(result)


def test_optional_dependencies_preserve_values_identities_and_order():
    records = [
        {"url": "https://A.example:443/", "value": "yes", "upstream": ["https://origin.example"]},
        {"url": "https://b.example", "value": "yes", "upstream": ["https://origin.example"]},
        {"url": "https://c.example", "value": "no", "upstream": []},
    ]
    evaluation = evaluate(records)
    result = {"evaluation": evaluation, **reconstruct_context(evaluation, mapped_chunks(evaluation), token_budget=100)}
    default = serialize_context_result(result)
    payload = serialize_context_result(result, include_dependencies=True)
    pairs = payload["evaluation"].pop("pairwise_dependencies")
    assert payload == default
    expected = []
    for pair in evaluation.pairwise_dependencies:
        identities = [serialize_source(s.kind, canonicalize_source(s.kind, s.identifier)).hex()
                      for s in (pair.source_a, pair.source_b)]
        assert set(identities) <= default["evaluation"]["source_reliability"].keys()
        expected.append({"source_a": identities[0], "source_b": identities[1], "dependency": pair.dependency})
    assert pairs == sorted(expected, key=lambda p: (p["source_a"], p["source_b"]))
    assert {p["dependency"] for p in pairs} == {0.0, 1.0}
    reversed_result = {**result, "evaluation": evaluate(list(reversed(records)))}
    assert serialize_context_result(reversed_result, include_dependencies=True) == serialize_context_result(result, include_dependencies=True)
    single = evaluate([{"url": "https://single.example", "value": "yes"}])
    empty = {"evaluation": single, **reconstruct_context(single, [], token_budget=0)}
    assert serialize_context_result(empty, include_dependencies=True)["evaluation"]["pairwise_dependencies"] == []
    json.dumps(serialize_context_result(result, include_dependencies=True), allow_nan=False)


@pytest.mark.parametrize("persist", [False, True])
@pytest.mark.parametrize("collect", [False, True])
@pytest.mark.parametrize("include", [False, True])
def test_optional_telemetry_collection_logging_and_history(runtime, tmp_path, monkeypatch, caplog, persist, collect, include):
    from omneum import evaluate_context
    from test_execution_history import history

    caplog.set_level(logging.INFO, logger="omneum.execution")
    config, evaluator, observations, estimator = runtime
    evaluation = evaluate_context(observations, estimator=estimator)
    chunks = mapped_chunks(evaluation)
    storage = SQLiteStorage(tmp_path / "optional.db")
    client = OmneumClient(config, evaluator,
        local_persistence=LocalPersistenceConfig(storage) if persist else None)
    samples = []
    original = _peak_process_memory_bytes
    def sample():
        samples.append(True)
        return original()
    monkeypatch.setattr("omneum.client._peak_process_memory_bytes", sample)
    payloads = []
    for budget in (0, 1000):
        payload = asyncio.run(client.prepare_context(observations, chunks, estimator=estimator,
            token_budget=budget, collect_telemetry=collect, include_telemetry=include, include_dependencies=True))
        assert _execution_telemetry.get() is None
        assert json.loads(json.dumps(payload, allow_nan=False)) == payload
        structural = {key: value for key, value in payload.items() if key != "telemetry"}
        expected = {"evaluation": evaluation, **reconstruct_context(evaluation, chunks, token_budget=budget)}
        assert structural == serialize_context_result(expected,
            token_counter="unicode_word_punctuation_proxy", include_dependencies=True)
        assert ("telemetry" in payload) is include
        payloads.append(payload)
    assert evaluator.context_calls == 2
    assert len(samples) == (2 if persist or collect or include else 0)
    logs = [record.execution for record in caplog.records if record.name == "omneum.execution"]
    assert len(logs) == (2 if collect else 0)
    rows = history(storage) if persist else []
    assert len(rows) == (2 if persist else 0)
    if not persist:
        assert not storage.path.exists()
    for index, payload in enumerate(payloads):
        if include:
            telemetry = payload["telemetry"]
            assert set(telemetry) == {
                "sdk_end_to_end_latency_ms", "evaluation_latency_ms", "graph_evaluation_latency_ms",
                "mcp_roundtrip_latency_ms", "chunk_selection_latency_ms", "context_reconstruction_latency_ms",
                "local_inference_latency_ms", "cpu_time_ms", "peak_memory_bytes", "cpu_time_scope", "peak_memory_scope",
            }
            assert telemetry["sdk_end_to_end_latency_ms"] >= telemetry["evaluation_latency_ms"] >= telemetry["local_inference_latency_ms"]
            assert telemetry["cpu_time_scope"] == "sdk_process_during_evaluation"
            assert telemetry["peak_memory_scope"] == "sdk_process_lifetime_peak_rss"
            for name, value in telemetry.items():
                if name.endswith("_ms"):
                    assert value >= 0
                if collect:
                    assert value == logs[index][name]
                if persist:
                    assert value == rows[index][name]


@pytest.mark.parametrize("options", [{"include_telemetry": 1}, {"include_dependencies": "yes"}])
def test_invalid_diagnostic_options(runtime, options):
    config, evaluator, observations, estimator = runtime
    client = OmneumClient(config, evaluator, local_persistence=None)
    with pytest.raises(TypeError, match="must be bools"):
        asyncio.run(client.prepare_context(observations, [], estimator=estimator, token_budget=0, **options))
    assert evaluator.context_calls == 0


def test_returned_telemetry_rejects_nonfinite_values(runtime, monkeypatch):
    config, evaluator, observations, estimator = runtime
    client = OmneumClient(config, evaluator, local_persistence=None)
    monkeypatch.setattr("omneum.client._peak_process_memory_bytes", lambda: float("nan"))
    with pytest.raises(ValueError, match="JSON"):
        asyncio.run(client.prepare_context(observations, [], estimator=estimator, token_budget=0, include_telemetry=True))
    assert _execution_telemetry.get() is None


def test_reject_nonfinite_scores_and_inconsistent_order():
    result = result_fixture()
    result["chunks"][0]["score"] = float("nan")
    with pytest.raises(ValueError):
        serialize_context_result(result)
    result = result_fixture()
    result["selected_chunk_ids"].reverse()
    with pytest.raises(ValueError, match="order"):
        serialize_context_result(result)


@pytest.mark.parametrize("enabled", [False, True])
def test_sdk_persistence_and_measurements(runtime, tmp_path, monkeypatch, caplog, enabled):
    caplog.set_level(logging.INFO, logger="omneum.execution")
    config, evaluator, observations, estimator = runtime
    storage = SQLiteStorage(tmp_path / "agent.db")
    persistence = LocalPersistenceConfig(storage) if enabled else None
    client = OmneumClient(config, evaluator, local_persistence=persistence)
    baseline = asyncio.run(client._evaluate_context(observations, estimator=estimator))
    chunks = mapped_chunks(baseline)
    persisted = []
    if enabled:
        original = SQLiteStorage.persist_context
        def tracked(self, **kwargs):
            persisted.append(kwargs["evaluation"])
            return original(self, **kwargs)
        monkeypatch.setattr(SQLiteStorage, "persist_context", tracked)
    payload = asyncio.run(client.prepare_context(observations, chunks, estimator=estimator,
        token_budget=1000, count_tokens=len, token_counter_name="test_character_counter", collect_telemetry=True))
    assert _execution_telemetry.get() is None
    measurements = next(record.execution for record in caplog.records if record.name == "omneum.execution")
    assert "telemetry" not in payload
    assert payload["selection"]["token_counter"] == "test_character_counter"
    assert payload["selection"]["selected_tokens"] == len(payload["context"])
    assert measurements["cpu_time_ms"] >= 0
    assert measurements["local_inference_latency_ms"] >= 0
    assert measurements["evaluation_latency_ms"] >= measurements["local_inference_latency_ms"]
    assert measurements["cpu_time_scope"] == "sdk_process_during_evaluation"
    peak = measurements["peak_memory_bytes"]
    assert peak is None or type(peak) is int and peak >= 0
    assert measurements["peak_memory_scope"] == "sdk_process_lifetime_peak_rss"
    if enabled:
        assert payload == serialize_persisted(persisted[0], chunks)
        with storage.transaction() as db:
            assert db.execute("SELECT count(*) FROM evaluation_runs").fetchone() == (2,)
            assert db.execute("SELECT count(*) FROM observations").fetchone() == (6,)
            parameters = [json.loads(row[0]) for row in db.execute("SELECT parameters FROM evaluation_runs")]
            assert persisted[0].evaluation_latency_ms in [row["evaluation_latency_ms"] for row in parameters]
            stored_support = [row[0] for row in db.execute("SELECT support_score FROM claim_scores WHERE evaluation_run_id=(SELECT id FROM evaluation_runs ORDER BY rowid DESC LIMIT 1)")]
            assert sorted(stored_support) == sorted(payload["evaluation"]["claim_support"].values())
    else:
        assert not storage.path.exists()
    def unexpected():
        raise AssertionError("disabled persistence and diagnostics must not sample process resources")
    with monkeypatch.context() as disabled:
        if not enabled:
            disabled.setattr("omneum.client.time.process_time", unexpected)
            disabled.setattr("omneum.client._peak_process_memory_bytes", unexpected)
        plain = asyncio.run(client.prepare_context(observations, chunks, estimator=estimator, token_budget=1000))
        assert "telemetry" not in plain
        assert plain["selection"]["token_counter"] == "unicode_word_punctuation_proxy"
    with pytest.raises(ValueError):
        asyncio.run(client.prepare_context(observations, chunks, estimator=estimator, token_budget=-1,
                    collect_telemetry=True))
    assert _execution_telemetry.get() is None
    with pytest.raises(ValueError, match="must not be empty"):
        asyncio.run(client.prepare_context([], [], estimator=estimator, token_budget=0))


def serialize_persisted(evaluation, chunks):
    original = serialize_context_result(dict(evaluation=evaluation, **reconstruct_context(evaluation, chunks,
        token_budget=1000, count_tokens=len)), token_counter="test_character_counter")
    return original


def test_memory_units_and_unsupported_platform(monkeypatch):
    resource = pytest.importorskip("resource")
    from types import SimpleNamespace
    monkeypatch.setattr(resource, "getrusage", lambda who: SimpleNamespace(ru_maxrss=12))
    for platform, expected in (("darwin", 12), ("linux", 12288), ("win32", None)):
        monkeypatch.setattr("omneum.metrics.sys.platform", platform)
        assert _peak_process_memory_bytes() == expected


def test_instrumentation_sampling_overhead():
    trials, samples = 1000, []
    for _ in range(5):
        started = perf_counter()
        for _ in range(trials):
            perf_counter()
            process_time()
            perf_counter()
            perf_counter()
            process_time()
            _peak_process_memory_bytes()
        samples.append((perf_counter()-started)*1e6/trials)
    assert all(math.isfinite(value) and value >= 0 for value in samples)
    print("telemetry sampling microseconds/evaluation:", sorted(samples)[2])


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("include", [False, True])
def test_agent_json_over_real_stdio(example_daemon, computed, tmp_path, monkeypatch, caplog, capfd, enabled, include):
    caplog.set_level(logging.INFO, logger="omneum.execution")
    import os
    from omneum import OmneumClientConfig, open_stdio_client
    from omneum.client import _evaluate_context as evaluate_context
    from omneum.mcp import ClientSession, StdioServerParameters

    observations, estimator = computed[4], computed[3]
    expected = evaluate_context(observations, estimator=estimator)
    chunks = mapped_chunks(expected)
    chunks.append({**chunks[0], "chunk_id": "discarded-copy", "raw_text": "Do not send this private duplicate."})
    storage = SQLiteStorage(tmp_path / "agent-stdio.db")
    persistence = LocalPersistenceConfig(storage) if enabled else None
    requests, responses = [], []
    original = ClientSession.call_tool
    async def tracked(self, name, arguments=None, *args, **kwargs):
        if name == "evaluate_context":
            requests.append(deepcopy(arguments))
        response = await original(self, name, arguments, *args, **kwargs)
        if name == "evaluate_context":
            responses.append(response.structuredContent)
        return response
    monkeypatch.setattr(ClientSession, "call_tool", tracked)
    async def run():
        server = StdioServerParameters(command=sys.executable, args=["-m", "omneum.server"], env=dict(os.environ))
        async with open_stdio_client(OmneumClientConfig.from_local_deployment(), server,
                                     local_persistence=persistence) as client:
            evaluated = await client._evaluate_context(observations, estimator=estimator)
            baseline = {"evaluation": evaluated, **reconstruct_context(evaluated, chunks,
                token_budget=1000, count_tokens=len)}
            if enabled:
                with storage.transaction() as db:
                    db.execute("UPDATE source_scores SET reliability_score=0")
                    db.execute("UPDATE claim_scores SET support_score=0")
            packet = await client.prepare_context(observations, chunks, estimator=estimator,
                token_budget=1000, count_tokens=len, token_counter_name="test_character_counter", collect_telemetry=True,
                include_dependencies=include, include_telemetry=include)
        projection = serialize_context_result(baseline, token_counter="test_character_counter", include_dependencies=include)
        assert packet["evaluation"] == projection["evaluation"]
        for field in ("source_reliability", "claim_support", "max_claim_support", "converged", "iterations", "convergence_delta"):
            assert packet["evaluation"][field] == projection["evaluation"][field]
        for field in ("selection", "chunks", "context", "packed_chunk_ids"):
            assert packet[field] == projection[field]
        measurements = next(record.execution for record in caplog.records if record.name == "omneum.execution")
        assert measurements["cpu_time_ms"] >= 0
        assert measurements["local_inference_latency_ms"] >= 0
        assert measurements["sdk_end_to_end_latency_ms"] >= measurements["evaluation_latency_ms"]
        assert measurements["mcp_roundtrip_latency_ms"] >= 0
        assert measurements["chunk_selection_latency_ms"] >= 0
        assert measurements["context_reconstruction_latency_ms"] >= 0
        assert ("telemetry" in packet) is include
        if include:
            assert packet["telemetry"] == {name: measurements[name] for name in packet["telemetry"]}
        assert "latency_ms" not in packet["evaluation"]
        assert "discarded-copy" not in packet["packed_chunk_ids"]
        artifact = tmp_path / "agent-result.json"
        artifact.write_text(json.dumps(packet, allow_nan=False, indent=2))
        assert json.loads(artifact.read_text()) == packet
        return packet
    packet = asyncio.run(run())
    assert _execution_telemetry.get() is None
    assert requests[0] == requests[1]
    captured = capfd.readouterr()
    assert captured.out == captured.err == ""
    wire = json.dumps(requests)
    assert all(chunk["raw_text"] not in wire and chunk["chunk_id"] not in wire for chunk in chunks)
    # The MCP response contract is unchanged by the extra client projection.
    assert set(responses[0]) == set(responses[1]) == {
        "protocol_version", "deployment_id", "voprf_key_version", "voprf_mode", "voprf_ciphersuite",
        "linkage_encoding_version", "evaluation_latency_ms", "summary", "source_reliability", "claim_support", "metadata"}
    if enabled:
        with storage.transaction() as db:
            assert db.execute("SELECT count(*) FROM evaluation_runs").fetchone() == (2,)
            assert db.execute("SELECT count(*) FROM observations").fetchone() == (6,)
            assert db.execute("SELECT count(*) FROM observation_source_references").fetchone()[0] > 0
            assert db.execute("SELECT count(*) FROM assertion_observations").fetchone() == (6,)
            assert db.execute("SELECT count(*) FROM source_scores").fetchone() == (4,)
            assert db.execute("SELECT count(*) FROM claim_scores").fetchone() == (4,)
            assert db.execute("SELECT count(*) FROM source_dependencies").fetchone() == (2,)
            assert db.execute("SELECT count(*) FROM source_scores WHERE reliability_score=0").fetchone() == (2,)
            stored = db.execute("SELECT support_score FROM claim_scores WHERE evaluation_run_id=(SELECT id FROM evaluation_runs ORDER BY rowid DESC LIMIT 1)").fetchall()
            assert sorted(row[0] for row in stored) == sorted(packet["evaluation"]["claim_support"].values())
    else:
        assert not storage.path.exists()


def test_prepare_is_primary_sdk_api():
    import omneum
    from omneum import client as client_module
    for name in ("evaluate_context_with_chunks_json", "serialize_context_result"):
        assert not hasattr(OmneumClient, name)
    assert omneum.evaluate_context is client_module._evaluate_context
    assert omneum.evaluate_records is evaluate
    assert OmneumClient.evaluate_context is OmneumClient._evaluate_context
    assert OmneumClient.evaluate_mapped is OmneumClient._evaluate_mapped
    assert hasattr(OmneumClient, "evaluate_context_with_chunks")
    assert not hasattr(omneum, "serialize_context_result")
    assert hasattr(OmneumClient, "prepare_context")


def test_legacy_sdk_calls_use_the_same_evaluation_and_reconstruction(runtime):
    from omneum import ContextMapper, evaluate_context

    config, evaluator, observations, estimator = runtime
    client = OmneumClient(config, evaluator, local_persistence=None)
    mapper = ContextMapper(
        source=lambda o: o.source,
        entity_namespace=lambda o: o.claim.entity_namespace,
        entity=lambda o: o.claim.entity,
        attribute=lambda o: o.claim.attribute,
        value=lambda o: o.claim.value,
        observation_id=lambda o: o.observation_id,
        observed_at=lambda o: o.observed_at,
        source_modified_at=lambda o: o.source_modified_at,
        upstream_sources=lambda o: o.upstream_sources,
        cited_sources=lambda o: o.cited_sources,
        parent_observation_ids=lambda o: o.parent_observation_ids,
        retrievals=lambda o: o.retrievals,
    )

    async def run():
        evaluation = await client.evaluate_context(observations, estimator=estimator)
        assert evaluation == evaluate_context(observations, estimator=estimator)
        assert await client.evaluate_mapped(observations, mapper, estimator=estimator) == evaluation
        chunks = mapped_chunks(evaluation)
        legacy = await client.evaluate_context_with_chunks(
            observations=observations, chunks=chunks, estimator=estimator, token_budget=100,
        )
        assert legacy == {"evaluation": evaluation, **reconstruct_context(evaluation, chunks, token_budget=100)}
        prepared = await client.prepare_context(observations, chunks, estimator=estimator, token_budget=100)
        assert prepared == serialize_context_result(legacy, token_counter="unicode_word_punctuation_proxy")

    asyncio.run(run())


def test_prepare_silent_and_verbose_claim_summary(runtime, capsys):
    config, evaluator, observations, estimator = runtime
    client = OmneumClient(config, evaluator, local_persistence=None)
    baseline = asyncio.run(client._evaluate_context(observations, estimator=estimator))
    chunks = mapped_chunks(baseline)
    quiet = asyncio.run(client.prepare_context(observations, chunks, estimator=estimator, token_budget=1000))
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
    verbose = asyncio.run(client.prepare_context(observations, chunks, estimator=estimator, token_budget=1000, verbose=True))
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("Omneum Evaluation\n\n")
    assert "Return window" in captured.err and "Shipping time" in captured.err
    assert captured.err.count("Support:") == 2
    for item in baseline.claim_support:
        assert item.claim.value in captured.err
        assert f"Support: {item.support:.2f}" in captured.err
    for forbidden in ("latency", "Supporting sources", "independent", "coverage", "Explanation", "CPU", "memory"):
        assert forbidden not in captured.err
    assert quiet == verbose
    assert json.loads(json.dumps(quiet, allow_nan=False)) == quiet
    assert set(quiet) == {"evaluation", "selection", "packed_chunk_ids", "chunks", "context"}
    assert not {"latency_ms", "telemetry", "cpu_time_ms", "peak_memory_bytes", "explanation"} & quiet["evaluation"].keys()
