import re


def normalize(text):
    return " ".join(
        re.sub(r"[^\w\s]", " ", text.lower()).split()
    )


def score_answer(answer, truth):
    normalized = normalize(answer)

    required = [
        normalize(value)
        for value in truth.scoring.required
    ]
    forbidden = [
        normalize(value)
        for value in truth.scoring.forbidden
    ]

    if any(
        value and value in normalized
        for value in forbidden
    ):
        return "incorrect"

    if all(
        value and value in normalized
        for value in required
    ):
        return "correct"

    return "unscored"


def score_selection(selected, truth):
    selected = set(selected)
    expected = set(truth.supporting_sources)

    true_positive = len(selected & expected)
    false_positive = len(selected - expected)
    false_negative = len(expected - selected)

    precision = (
        true_positive / (true_positive + false_positive)
        if true_positive + false_positive
        else 0.0
    )
    recall = (
        true_positive / (true_positive + false_negative)
        if true_positive + false_negative
        else 0.0
    )

    return {
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": precision,
        "recall": recall,
    }
