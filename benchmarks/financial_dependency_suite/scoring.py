import json
from pathlib import Path


def load_ground_truth(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def expected_relationships(ground_truth):
    return {
        (item["source"], item["depends_on"])
        for item in ground_truth["documented_relationships"]
    }


def score_relationships(predicted, ground_truth):
    expected = expected_relationships(ground_truth)
    predicted = set(predicted)

    true_positive = len(predicted & expected)
    false_positive = len(predicted - expected)
    false_negative = len(expected - predicted)

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
