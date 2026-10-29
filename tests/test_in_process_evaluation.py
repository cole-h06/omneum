import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import runpy
import subprocess
import sys

import pytest

import omneum
from omneum import Claim, Observation, OmneumClient, Source
from omneum.client import _evaluate_context as evaluate_context
from omneum.context_selection import token_count
from omneum.dependency import InformationGraphError
import omneum.client as client_module


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/context_quality_demo/before_after.py"


def test_dependency_scoring(monkeypatch, capsys):
    calls = []
    selections = []
    reconstruct_context = omneum.reconstruct_context

    def capture(evaluation, chunks, **kwargs):
        before = deepcopy(chunks)
        result = reconstruct_context(evaluation, chunks, **kwargs)
        assert chunks == before
        selections.append((evaluation, chunks, kwargs, result))
        return result

    monkeypatch.setattr(omneum, "reconstruct_context", capture)
    for name in ("estimate_dependencies", "build_graph", "infer"):
        original = getattr(client_module, name)

        def wrapped(*args, _name=name, _original=original, **kwargs):
            calls.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(client_module, name, wrapped)

    namespace = runpy.run_path(str(EXAMPLE), run_name="__main__")
    assert calls == ["estimate_dependencies", "build_graph", "infer"]
    captured = capsys.readouterr()
    assert captured.out == ""
    output = captured.err
    assert output.index("Structural evaluation (all retrieved evidence)") < output.index("\nRaw RAG\n")
    assert "Context payload for the next LLM request:" not in output
    assert "source_reliability" not in output
    assert "pairwise_dependencies" not in output
    assert len(selections) == 2
    evaluation, chunks, options, raw = selections[0]
    other_evaluation, other_chunks, other_options, prepared = selections[1]
    assert other_evaluation is evaluation
    assert other_chunks is chunks
    assert options == {**other_options, "strategy": "retrieval"}
    assert other_options["strategy"] == "coverage_support"
    assert options["count_tokens"] is token_count
    assert raw["selected_chunk_ids"] == ["team-faq", "wiki-mirror", "gateway-config"]
    assert prepared["selected_chunk_ids"] == ["security-policy", "audit-config"]
    assert raw["token_usage"] == 75
    assert prepared["token_usage"] == 51
    for label, result in (("Raw RAG", raw), ("Omneum", prepared)):
        selected = [chunk for identifier in result["selected_chunk_ids"]
                    for chunk in chunks if chunk["chunk_id"] == identifier]
        covered = {identifier for chunk in selected for identifier in chunk["claim_ids"]}
        assert result["covered_claim_ids"] == sorted(covered)
        assert result["claim_coverage"] == {"covered": len(covered), "total": 4}
        assert result["token_usage"] == token_count(result["context"]) <= options["token_budget"]
        assert result["context"] == "\n\n".join(
            f"[{chunk['chunk_id']}]\n{chunk['raw_text']}" for chunk in selected
        )
        section = output.split(f"\n{label}\n", 1)[1].split("\nOmneum\n", 1)[0]
        assert "Selected (rendering order): " + ", ".join(result["selected_chunk_ids"]) in section
        assert f"Token usage: {result['token_usage']}/{options['token_budget']}" in section
        assert f"Claim coverage: {len(covered)}/4" in section
        excluded = [chunk["chunk_id"] for chunk in chunks
                    if chunk["chunk_id"] not in result["selected_chunk_ids"]]
        assert "Excluded: " + ", ".join(excluded) in section
        assert result["context"] not in output
    claims = {item.claim.attribute: item for item in evaluation.claim_support}
    assert claims["processing_region"].supporting_source_count == 4
    assert claims["processing_region"].estimated_independent_support_count == 2.0
    assert claims["customer_content"].estimated_independent_support_count == 2.0
    assert evaluation.convergence.converged
    assert math.isfinite(evaluation.evaluation_latency_ms)
    assert evaluation.evaluation_latency_ms >= 0
    structural = output.split("Structural evaluation (all retrieved evidence)\n", 1)[1].split("\nRaw RAG", 1)[0]
    assert [line.strip().split(":", 1)[0] for line in structural.splitlines()] == sorted(claims)
    for attribute, item in claims.items():
        assert re.search(
            rf"(?m)^  {attribute}: +{item.supporting_source_count} sources, "
            rf"{item.estimated_independent_support_count:.2f} estimated independent support$",
            structural,
        )

    results = namespace["main"]()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == output
    assert results == {"evaluation": evaluation, "raw_rag": raw, "omneum": prepared}
    assert selections[2][3] == raw
    assert selections[3][3] == prepared


@pytest.mark.parametrize("debug", [False, True])
def test_demo_debug_json(debug, monkeypatch, capsys):
    namespace = runpy.run_path(str(EXAMPLE))
    main = namespace["main"]
    assert main.__globals__["DEBUG_JSON"] is False
    monkeypatch.setitem(main.__globals__, "DEBUG_JSON", debug)
    results = main()
    captured = capsys.readouterr()
    assert "Structural evaluation (all retrieved evidence)" in captured.err
    assert "\nRaw RAG\n" in captured.err and "\nOmneum\n" in captured.err
    assert "Context payload for the next LLM request:" not in captured.err
    if not debug:
        assert captured.out == ""
        return

    payload = json.loads(captured.out)
    assert captured.out.startswith('{\n  "evaluation": {\n')
    assert set(payload) == {"evaluation", "raw_rag", "omneum"}
    evaluation = results["evaluation"]
    assert len(payload["evaluation"]["source_reliability"]) == len(evaluation.source_reliability)
    for actual, expected in zip(payload["evaluation"]["claim_support"], evaluation.claim_support):
        assert actual["claim"]["value"] == expected.claim.value
        assert "_value_bytes" not in actual["claim"]
        assert actual["support"] == expected.support
        assert actual["supporting_source_count"] == expected.supporting_source_count
    pairs = payload["evaluation"]["pairwise_dependencies"]
    assert len(pairs) == len(evaluation.pairwise_dependencies)
    for actual, expected in zip(pairs, evaluation.pairwise_dependencies):
        assert actual["dependency"] == expected.dependency
        assert actual["source_a"]["identifier"] == expected.source_a.identifier
        assert actual["source_b"]["identifier"] == expected.source_b.identifier
        assert "signals" in actual and "evidence" in actual
    assert payload["evaluation"]["evaluation_latency_ms"] == evaluation.evaluation_latency_ms
    assert payload["evaluation"]["convergence"]["converged"] is True
    for label in ("raw_rag", "omneum"):
        assert payload[label] == results[label]
        assert payload[label]["context"] not in captured.err
    json.dumps(payload, allow_nan=False)


def test_client_parity(tmp_path):
    from test_client import make_config, make_server
    from test_client_evaluation import Evaluator, estimator, observations

    async def run():
        server = make_server(tmp_path)
        client = OmneumClient(make_config(server), Evaluator(server), local_persistence=None)
        values = observations()
        values = (*values, replace(
            values[1], observation_id="c1",
            source=replace(values[1].source, identifier="https://c.example"),
            claim=Claim("service", "Product", "Return Window", "60 days"),
        ))
        config = estimator(threshold=0.5)
        remote = await client._evaluate_context(values, estimator=config)
        local = evaluate_context(values, estimator=config)
        assert local.claim_support == remote.claim_support
        assert set(local.source_reliability) == set(remote.source_reliability)
        assert local.pairwise_dependencies == remote.pairwise_dependencies
        assert local.convergence == remote.convergence

    asyncio.run(run())


def test_invalid_observations():
    from test_client_evaluation import estimator as make_estimator

    estimator = make_estimator()
    with pytest.raises(InformationGraphError, match="empty"):
        evaluate_context([], estimator=estimator)
    with pytest.raises(TypeError, match="Observation"):
        evaluate_context([object()], estimator=estimator)
    observation = Observation(
        observation_id="a", source=Source("web_document", "https://a.example"),
        claim=Claim("records", "default", "value", 1),
        observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    with pytest.raises(InformationGraphError, match="duplicate"):
        evaluate_context([observation, observation], estimator=estimator)
    conflicting_owner = replace(
        observation, observation_id="other",
        source=replace(observation.source, owner_id="other-owner"),
    )
    with pytest.raises(InformationGraphError, match="conflicting owners"):
        evaluate_context([observation, conflicting_owner], estimator=estimator)


def normalize_output(text):
    return re.sub(
        r"(?m)^Evaluation latency: \d+(?:\.\d+)? ms$",
        "Evaluation latency: <elapsed> ms",
        text,
    ).strip()


@pytest.mark.parametrize("example", ["sdk", "script"])
def test_evaluate_without_daemon(tmp_path, capsys, example):
    if example == "sdk":
        sdk = (ROOT / "docs/sdk.md").read_text()
        blocks = re.findall(r"```(\w+)\n(.*?)```", sdk, re.DOTALL)
        snippet = next(code for language, code in blocks
                       if language == "python" and "omneum.evaluate(" in code)
        exec(snippet, {"__name__": "__main__"})
    else:
        snippet = EXAMPLE.read_text()
        runpy.run_path(str(EXAMPLE), run_name="__main__")
    expected = capsys.readouterr()
    assert (expected.out if example == "sdk" else expected.err).strip()

    harness = '''
import sys
sys.path.insert(0, sys.argv[1])
def audit(event, args):
    if event.startswith(("socket.", "subprocess.", "sqlite3.", "os.spawn", "os.exec")):
        raise AssertionError("External execution or database access: " + event)
    if event == "open":
        mode, flags = args[1], args[2]
        if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (flags & 3):
            raise AssertionError("File write: " + str(args[0]))
sys.addaudithook(audit)
exec(sys.argv[2])
'''
    completed = subprocess.run(
        [sys.executable, "-B", "-c", harness, str(ROOT), snippet],
        cwd=tmp_path, capture_output=True, text=True, check=True,
    )
    assert normalize_output(completed.stdout) == normalize_output(expected.out)
    assert normalize_output(completed.stderr) == normalize_output(expected.err)
    assert list(tmp_path.iterdir()) == []
