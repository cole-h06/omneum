from collections import defaultdict


def summarize(records):
    grouped = defaultdict(list)

    for record in records:
        grouped[record["method"]].append(record)

    summary = {}

    for method, items in grouped.items():
        attempted = len(items)
        correct = sum(
            item.get("answer_score") == "correct"
            for item in items
        )
        incorrect = sum(
            item.get("answer_score") == "incorrect"
            for item in items
        )
        unscored = sum(
            item.get("answer_score") == "unscored"
            for item in items
        )
        failures = attempted - correct - incorrect - unscored
        evaluable = correct + incorrect

        selection_scores = [
            item["selection_score"]
            for item in items
            if item.get("selection_score") is not None
        ]

        summary[method] = {
            "attempted": attempted,
            "correct": correct,
            "incorrect": incorrect,
            "unscored": unscored,
            "failures": failures,
            "accuracy": (
                correct / attempted
                if attempted
                else 0.0
            ),
            "evaluable_accuracy": (
                correct / evaluable
                if evaluable
                else None
            ),
            "selection_precision": (
                sum(
                    score["precision"]
                    for score in selection_scores
                )
                / len(selection_scores)
                if selection_scores
                else None
            ),
            "selection_recall": (
                sum(
                    score["recall"]
                    for score in selection_scores
                )
                / len(selection_scores)
                if selection_scores
                else None
            ),
        }

    return summary
