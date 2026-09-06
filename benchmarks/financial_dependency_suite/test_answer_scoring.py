from benchmarks.financial_dependency_suite.answer_scoring import (
    score_money_answer,
)


def test_correct_answer():
    assert score_money_answer(
        "Arm reported revenue of $2.679 billion.",
        correct=2_679_000_000,
        false=3_200_000_000,
    ) == "correct"


def test_false_answer():
    assert score_money_answer(
        "Revenue was $3.2 billion.",
        correct=2_679_000_000,
        false=3_200_000_000,
    ) == "false"


def test_ambiguous_answer():
    assert score_money_answer(
        "Sources report $2.679 billion and $3.2 billion.",
        correct=2_679_000_000,
        false=3_200_000_000,
    ) == "ambiguous"


def test_unscored_answer():
    assert score_money_answer(
        "The sources conflict.",
        correct=2_679_000_000,
        false=3_200_000_000,
    ) == "unscored"


def test_value_answer():
    from benchmarks.financial_dependency_suite.answer_scoring import (
        score_value_answer,
    )

    assert score_value_answer(
        "The retention period is 90 days.",
        correct=90,
        false=30,
        unit="days",
    ) == "correct"

    assert score_value_answer(
        "The retention period is 30 days.",
        correct=90,
        false=30,
        unit="days",
    ) == "false"

    assert score_value_answer(
        "Sources report both 30 days and 90 days.",
        correct=90,
        false=30,
        unit="days",
    ) == "ambiguous"


def test_smci_answer_scoring():
    from .answer_scoring import score_smci_answer

    assert score_smci_answer(
        "EY concluded that it could no longer rely on "
        "representations from management and the Audit Committee."
    ) == "correct"

    assert score_smci_answer(
        "EY was unwilling to remain associated with "
        "management's financial statements."
    ) == "correct"

    assert score_smci_answer(
        "EY resigned because of a disagreement over audit fees."
    ) == "false"

    assert score_smci_answer(
        "EY could no longer rely on management, although reports "
        "also attributed the resignation to an audit fee dispute."
    ) == "ambiguous"

    assert score_smci_answer(
        "EY resigned following concerns at the company."
    ) == "unscored"
