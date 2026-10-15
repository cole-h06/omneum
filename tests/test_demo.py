import subprocess
import sys

import omneum
from omneum.demo import main
from omneum.explanations import explain_evaluation

from test_in_process_evaluation import ROOT, normalize_output


def test_demo_evaluation(monkeypatch, capsys):
    evaluations = []
    evaluate = omneum.evaluate

    def capture(observations):
        result = evaluate(observations)
        evaluations.append(result)
        return result

    monkeypatch.setattr(omneum, "evaluate", capture)

    main()

    assert len(evaluations) == 1
    result = evaluations[0]
    assert capsys.readouterr().out == explain_evaluation(result) + "\n"
    claims = {item.claim.value: item for item in result.claim_support}
    assert set(claims) == {4200000000, 3900000000}
    assert claims[4200000000].supporting_source_count == 3
    assert claims[4200000000].estimated_independent_support_count == 2.0
    assert claims[3900000000].supporting_source_count == 1
    assert claims[3900000000].estimated_independent_support_count == 1.0
    for value, conflict in ((4200000000, 3900000000), (3900000000, 4200000000)):
        assert len(claims[value].conflicting_claims) == 1
        assert claims[value].conflicting_claims[0].claim == claims[conflict].claim
        assert claims[value].conflicting_claims[0].support == claims[conflict].support
    assert sorted(pair.dependency for pair in result.pairwise_dependencies) == [
        0.0, 0.0, 0.0, 0.0, 0.0, 1.0,
    ]
    assert result.convergence.converged


def test_demo_without_daemon(tmp_path, capsys):
    main()
    expected = capsys.readouterr().out
    harness = '''
import runpy
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
runpy.run_module("omneum.demo", run_name="__main__")
'''
    completed = subprocess.run(
        [sys.executable, "-B", "-c", harness, str(ROOT)],
        cwd=tmp_path, capture_output=True, text=True, check=True,
    )
    assert normalize_output(completed.stdout) == normalize_output(expected)
    assert completed.stderr == ""
    assert list(tmp_path.iterdir()) == []
