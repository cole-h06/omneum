import asyncio
from dataclasses import replace
from pathlib import Path
import runpy
import subprocess
import sys

import pytest

from omneum import Claim, OmneumClient, evaluate_context
from omneum.dependency import InformationGraphError
import omneum.client as client_module


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/python_quick_start.py"


def example():
    return runpy.run_path(str(EXAMPLE))


def test_dependency_aware_real_pipeline(monkeypatch, capsys):
    calls = []
    for name in ("estimate_dependencies", "build_graph", "infer"):
        original = getattr(client_module, name)

        def wrapped(*args, _name=name, _original=original, **kwargs):
            calls.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(client_module, name, wrapped)

    namespace = example()
    assert calls == ["estimate_dependencies", "build_graph", "infer"]
    assert capsys.readouterr().out == "Estimated independent support: 2.00\n"
    result = namespace["result"]
    claim = result.claim_support[0]
    assert claim.supporting_source_count == 3
    assert claim.estimated_independent_support_count == 2.0
    assert sorted(pair.dependency for pair in result.pairwise_dependencies) == [0.0, 0.0, 1.0]
    assert result.convergence.converged

    independent = [replace(o, upstream_sources=()) for o in namespace["observations"]]
    result = evaluate_context(independent, estimator=namespace["estimator"])
    assert result.claim_support[0].estimated_independent_support_count == 3.0


def test_matches_existing_sdk_pipeline(tmp_path):
    from test_client import make_config, make_server
    from test_client_assertion_evaluation import Evaluator, estimator, observations

    async def run():
        server = make_server(tmp_path)
        client = OmneumClient(make_config(server), Evaluator(server), local_persistence=None)
        values = observations()
        # Include a conflicting claim and exercise the shared cluster mapping.
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


def test_validates_observations():
    namespace = example()
    estimator = namespace["estimator"]
    with pytest.raises(InformationGraphError, match="empty"):
        evaluate_context([], estimator=estimator)
    with pytest.raises(TypeError, match="Observation"):
        evaluate_context([object()], estimator=estimator)
    observation = namespace["observations"][0]
    with pytest.raises(InformationGraphError, match="duplicate"):
        evaluate_context([observation, observation], estimator=estimator)
    conflicting_owner = replace(
        observation, observation_id="other",
        source=replace(observation.source, owner_id="other-owner"),
    )
    with pytest.raises(InformationGraphError, match="conflicting owners"):
        evaluate_context([observation, conflicting_owner], estimator=estimator)


def test_readme_example_without_services_or_persistence(tmp_path):
    readme = (ROOT / "README.md").read_text()
    section = readme.split("### Try Omneum in Python\n", 1)[1].split("### 2.", 1)[0]
    snippet = section.split("```python\n", 1)[1].split("```", 1)[0]
    expected = section.split("```text\n", 1)[1].split("```", 1)[0]
    assert snippet.strip() == EXAMPLE.read_text().split("\n\n", 1)[1].strip()
    assert readme.index("pip install omneum\n```") < readme.index("### Try Omneum in Python") < readme.index("omneum install\n```")

    # Reject network, subprocess, database, and filesystem writes.
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
    assert completed.stdout == expected
    assert completed.stderr == ""
    assert list(tmp_path.iterdir()) == []
