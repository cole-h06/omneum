import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import math
from pathlib import Path
import re
import runpy
import subprocess
import sys

import pytest

from omneum import Claim, Observation, OmneumClient, Source, evaluate_context
from omneum.dependency import InformationGraphError
import omneum.client as client_module


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/python_quick_start.py"


def test_dependency_scoring(monkeypatch, capsys):
    calls = []
    for name in ("estimate_dependencies", "build_graph", "infer"):
        original = getattr(client_module, name)

        def wrapped(*args, _name=name, _original=original, **kwargs):
            calls.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(client_module, name, wrapped)

    namespace = runpy.run_path(str(EXAMPLE))
    assert calls == ["estimate_dependencies", "build_graph", "infer"]
    assert "Estimated independent support: 2.00" in capsys.readouterr().out
    result = namespace["result"]
    claim = result.claim_support[0]
    assert claim.supporting_source_count == 3
    assert claim.estimated_independent_support_count == 2.0
    assert sorted(pair.dependency for pair in result.pairwise_dependencies) == [0.0, 0.0, 1.0]
    assert result.convergence.converged
    assert math.isfinite(result.evaluation_latency_ms)
    assert result.evaluation_latency_ms >= 0


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
        remote = await client.evaluate_context(values, estimator=config)
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


@pytest.mark.parametrize("example", ["readme", "script"])
def test_evaluate_without_daemon(tmp_path, example):
    readme = (ROOT / "README.md").read_text()
    blocks = re.findall(r"```(\w+)\n(.*?)```", readme, re.DOTALL)
    index, snippet = next(
        (i, code) for i, (language, code) in enumerate(blocks)
        if language == "python" and "omneum.evaluate(" in code
    )
    expected = next(code for language, code in blocks[index + 1:] if language == "text")
    if example == "script":
        snippet = EXAMPLE.read_text()

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
    assert normalize_output(completed.stdout) == normalize_output(expected)
    assert completed.stderr == ""
    assert list(tmp_path.iterdir()) == []
