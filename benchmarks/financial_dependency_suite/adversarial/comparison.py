import statistics

from ..llm_judge import judge_dependencies_from_results


LLM_JUDGES = (
    ("anthropic", "claude-sonnet-5"),
    ("openai", "gpt-6-astra"),
    ("google", "gemini-3.8-flash"),
)


def mean_or_none(values):
    return statistics.mean(values) if values else None


def score_relationships(relationships, expected):
    predicted = {
        frozenset((
            relationship["source"],
            relationship["depends_on"],
        ))
        for relationship in relationships
    }
    expected = {
        frozenset(pair)
        for pair in expected
    }

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
        else 1.0
    )

    return {
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": precision,
        "recall": recall,
        "exact_match": predicted == expected,
    }


async def evaluate_llm_judges(
    *,
    query,
    results,
    expected_relationships,
    include_text=False,
):
    evaluations = {}

    for provider, model in LLM_JUDGES:
        try:
            judged = await judge_dependencies_from_results(
                query,
                results,
                provider=provider,
                model=model,
                include_text=include_text,
            )

            evaluations[model] = {
                "provider": provider,
                "model": model,
                "status": "completed",
                "relationships": judged["relationships"],
                "parse_error": judged["parse_error"],
                "scores": (
                    score_relationships(
                        judged["relationships"],
                        expected_relationships,
                    )
                    if judged["relationships"] is not None
                    else None
                ),
                "latency_seconds":
                    judged["generation"]["latency_seconds"],
                "input_tokens":
                    judged["generation"]["input_tokens"],
                "output_tokens":
                    judged["generation"]["output_tokens"],
                "raw_output":
                    judged["generation"]["text"],
            }

        except Exception as exc:
            evaluations[model] = {
                "provider": provider,
                "model": model,
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }

    return evaluations


def summarize_llm_judges(trials, condition):
    models = {}

    for provider, model in LLM_JUDGES:
        records = [
            trial[condition]["llm_judges"][model]
            for trial in trials
        ]

        completed = [
            record
            for record in records
            if record["status"] == "completed"
        ]

        valid = [
            record
            for record in completed
            if record["parse_error"] is None
            and record["scores"] is not None
        ]

        models[model] = {
            "provider": provider,
            "model": model,
            "attempted_trials": len(records),
            "completed_trials": len(completed),
            "provider_failures":
                len(records) - len(completed),
            "valid_output_trials": len(valid),
            "output_failures":
                len(completed) - len(valid),
            "availability_rate":
                len(completed) / len(records)
                if records else None,
            "valid_output_rate":
                len(valid) / len(completed)
                if completed else None,
            "exact_match_rate": mean_or_none([
                float(record["scores"]["exact_match"])
                for record in valid
            ]),
            "mean_precision": mean_or_none([
                record["scores"]["precision"]
                for record in valid
            ]),
            "mean_recall": mean_or_none([
                record["scores"]["recall"]
                for record in valid
            ]),
            "mean_latency_seconds": mean_or_none([
                record["latency_seconds"]
                for record in completed
            ]),
            "mean_input_tokens": mean_or_none([
                record["input_tokens"]
                for record in completed
            ]),
            "mean_output_tokens": mean_or_none([
                record["output_tokens"]
                for record in completed
            ]),
        }

    return models
