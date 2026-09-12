from benchmarks.financial_dependency_suite.heldout.schema import (
    AnswerScoring,
    GroundTruth,
)
from benchmarks.financial_dependency_suite.heldout.scoring import (
    score_answer,
)


def truth(required, forbidden=()):
    return GroundTruth(
        case_id="test",
        answer="expected",
        supporting_sources=("source_a",),
        scoring=AnswerScoring(
            required=tuple(required),
            forbidden=tuple(forbidden),
        ),
    )


def test_correct_answer():
    result = score_answer(
        "The reported total was $2.679 billion.",
        truth(["2.679 billion"]),
    )

    assert result == "correct"


def test_forbidden_answer():
    result = score_answer(
        "The reported total was $3.2 billion.",
        truth(
            ["2.679 billion"],
            ["3.2 billion"],
        ),
    )

    assert result == "incorrect"


def test_unscored_answer():
    result = score_answer(
        "The available context does not establish the total.",
        truth(["2.679 billion"]),
    )

    assert result == "unscored"


def test_forbidden_overrides_required():
    result = score_answer(
        "Sources report both 2.679 billion and 3.2 billion.",
        truth(
            ["2.679 billion"],
            ["3.2 billion"],
        ),
    )

    assert result == "incorrect"


def test_selection_score():
    from benchmarks.financial_dependency_suite.heldout.scoring import (
        score_selection,
    )

    result = score_selection(
        ["source_a", "source_b"],
        GroundTruth(
            case_id="test",
            answer="expected",
            supporting_sources=("source_a", "source_c"),
            scoring=AnswerScoring(
                required=("expected",),
                forbidden=(),
            ),
        ),
    )

    assert result == {
        "true_positive": 1,
        "false_positive": 1,
        "false_negative": 1,
        "precision": 0.5,
        "recall": 0.5,
    }


def test_selection_score_empty():
    from benchmarks.financial_dependency_suite.heldout.scoring import (
        score_selection,
    )

    result = score_selection(
        [],
        GroundTruth(
            case_id="test",
            answer="expected",
            supporting_sources=("source_a",),
            scoring=AnswerScoring(
                required=("expected",),
                forbidden=(),
            ),
        ),
    )

    assert result["precision"] == 0.0
    assert result["recall"] == 0.0
