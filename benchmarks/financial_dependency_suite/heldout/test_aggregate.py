from benchmarks.financial_dependency_suite.heldout.aggregate import (
    summarize,
)


def test_summary_denominator():
    records = [
        {
            "method": "test",
            "answer_score": "correct",
            "selection_score": {
                "precision": 1.0,
                "recall": 1.0,
            },
        },
        {
            "method": "test",
            "answer_score": "incorrect",
            "selection_score": {
                "precision": 0.5,
                "recall": 0.5,
            },
        },
        {
            "method": "test",
            "answer_score": "unscored",
            "selection_score": {
                "precision": 0.0,
                "recall": 0.0,
            },
        },
        {
            "method": "test",
            "answer_score": "selection_failure",
        },
    ]

    result = summarize(records)["test"]

    assert result["attempted"] == 4
    assert result["correct"] == 1
    assert result["incorrect"] == 1
    assert result["unscored"] == 1
    assert result["failures"] == 1
    assert result["accuracy"] == 0.25
    assert result["evaluable_accuracy"] == 0.5
    assert result["selection_precision"] == 0.5
    assert result["selection_recall"] == 0.5


def test_empty_summary():
    assert summarize([]) == {}
