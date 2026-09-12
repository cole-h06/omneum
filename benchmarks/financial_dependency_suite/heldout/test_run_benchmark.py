import json

from benchmarks.financial_dependency_suite.heldout.run_benchmark import (
    discover_cases,
)


def test_discover_cases(tmp_path):
    directory = tmp_path / "case_a"
    directory.mkdir()

    case = {
        "id": "case_a",
        "domain": "test",
        "question": "What is the value?",
        "context_budget": 1,
        "candidates": [],
    }

    truth = {
        "case_id": "case_a",
        "answer": "42",
        "supporting_sources": [],
        "scoring": {
            "required": ["42"],
            "forbidden": [],
        },
    }

    (directory / "case.json").write_text(
        json.dumps(case)
    )
    (directory / "ground_truth.json").write_text(
        json.dumps(truth)
    )

    discovered = discover_cases(tmp_path)

    assert len(discovered) == 1
    assert discovered[0][2].case_id == "case_a"
    assert discovered[0][3].case_id == "case_a"
