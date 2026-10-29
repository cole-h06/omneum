"""Aggregate held-out benchmark results and measurements."""

from collections import Counter, defaultdict
import math


def _number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _percentile(values, quantile):
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _distribution(values, attempted):
    return {
        "n": len(values),
        "coverage": len(values) / attempted if attempted else None,
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
    }


def _stage(record, name):
    value = record.get(name)
    return value if isinstance(value, dict) else {}


def _latencies(items, attempted):
    selection = [
        record["selection"]["latency_seconds"]
        for record in items
        if _number(_stage(record, "selection").get("latency_seconds"))
    ]
    generation = [
        record["generation"]["latency_seconds"]
        for record in items
        if _number(_stage(record, "generation").get("latency_seconds"))
    ]
    end_to_end = []
    for record in items:
        saved = record.get("end_to_end_latency_seconds")
        if _number(saved):
            end_to_end.append(saved)
            continue
        selection_latency = _stage(record, "selection").get("latency_seconds")
        generation_latency = _stage(record, "generation").get("latency_seconds")
        if _number(selection_latency) and _number(generation_latency):
            end_to_end.append(selection_latency + generation_latency)

    evaluator = []
    integration = []
    evaluator_input_tokens = []
    evaluator_output_tokens = []
    for record in items:
        selected = _stage(record, "selection")
        full = selected.get("cold_integration_latency_seconds")
        if not _number(full):
            full = selected.get("latency_seconds")
        evaluation = selected.get("evaluation_latency_seconds")
        if _number(evaluation):
            evaluator.append(evaluation)
        if _number(full) and _number(evaluation):
            # Prefer the Omneum integration clock to avoid including upstream
            # Claude/BGE/Cohere shortlist latency in this component.
            integration.append(full - evaluation)
        if _number(selected.get("evaluator_input_tokens")):
            evaluator_input_tokens.append(selected["evaluator_input_tokens"])
        if _number(selected.get("evaluator_output_tokens")):
            evaluator_output_tokens.append(selected["evaluator_output_tokens"])

    return {
        "selection_seconds": _distribution(selection, attempted),
        "generation_seconds": _distribution(generation, attempted),
        "omneum_evaluator_seconds": _distribution(evaluator, attempted),
        "omneum_integration_overhead_seconds": _distribution(integration, attempted),
        "evaluator_input_tokens": {"n": len(evaluator_input_tokens),
                                   "sum": sum(evaluator_input_tokens) if evaluator_input_tokens else None},
        "evaluator_output_tokens": {"n": len(evaluator_output_tokens),
                                    "sum": sum(evaluator_output_tokens) if evaluator_output_tokens else None},
        "end_to_end_seconds": _distribution(end_to_end, attempted),
        "percentile_method": "linear interpolation at (n - 1) * q; unavailable values excluded",
    }


def _generator_usage(items):
    input_values = []
    output_values = []
    total_values = []
    covered_correct = 0
    for record in items:
        generation = record.get("generation")
        if not isinstance(generation, dict):
            continue
        input_tokens = generation.get("input_tokens")
        output_tokens = generation.get("output_tokens")
        if _number(input_tokens):
            input_values.append(input_tokens)
        if _number(output_tokens):
            output_values.append(output_tokens)
        if _number(input_tokens) and _number(output_tokens):
            total_values.append(input_tokens + output_tokens)
            covered_correct += record.get("answer_score") == "correct"

    total = sum(total_values) if total_values else None
    # Correct answers per 1,000 observed downstream generator tokens.
    efficiency = (covered_correct * 1000 / total) if total else None
    return {
        "input_tokens": {"n": len(input_values), "sum": sum(input_values) if input_values else None},
        "output_tokens": {"n": len(output_values), "sum": sum(output_values) if output_values else None},
        "total_tokens": {"n": len(total_values), "sum": total},
        "token_efficiency": {
            "definition": "correct answers among records with complete generator usage per 1,000 downstream generator input-plus-output tokens",
            "correct_answers": covered_correct,
            "usage_covered_records": len(total_values),
            "correct_per_1000_tokens": efficiency,
        },
    }


def _inference_cost(items):
    # This repository has no configured provider or inference price table.
    return {"usd": None, "availability": "no_pricing_defined"}


def summarize(records):
    grouped = defaultdict(list)
    for record in records:
        grouped[record["method"]].append(record)

    summary = {}
    for method, items in grouped.items():
        attempted = len(items)
        correct = sum(item.get("answer_score") == "correct" for item in items)
        incorrect = sum(item.get("answer_score") == "incorrect" for item in items)
        unscored = sum(item.get("answer_score") == "unscored" for item in items)
        failures = attempted - correct - incorrect - unscored
        evaluable = correct + incorrect
        selection_scores = [item["selection_score"] for item in items
                            if item.get("selection_score") is not None]
        summary[method] = {
            "attempted": attempted,
            "correct": correct,
            "incorrect": incorrect,
            "unscored": unscored,
            "failures": failures,
            "selection_failures": sum(item.get("answer_score") == "selection_failure" for item in items),
            "generation_failures": sum(item.get("answer_score") == "generation_failure" for item in items),
            "generation_failure_types": dict(sorted(Counter(
                item.get("failure_type", "unknown") for item in items
                if item.get("answer_score") == "generation_failure"
            ).items())),
            "accuracy": correct / attempted if attempted else 0.0,
            "evaluable_accuracy": correct / evaluable if evaluable else None,
            "selection_precision": (sum(s["precision"] for s in selection_scores) / len(selection_scores)
                                    if selection_scores else None),
            "selection_recall": (sum(s["recall"] for s in selection_scores) / len(selection_scores)
                                 if selection_scores else None),
            "generator_usage": _generator_usage(items),
            "latency": _latencies(items, attempted),
            "inference_cost": _inference_cost(items),
        }
        # Additive diagnostics only for newly instrumented records. Historical
        # summaries retain their shape; never mix count and token ceilings.
        budget_groups = defaultdict(list)
        for item in items:
            metric = item.get("budget_aware_selection")
            if metric:
                budget_groups[(metric["metric_version"], metric["budget_type"])].append(metric)
        if budget_groups:
            summary[method]["budget_aware_selection"] = [
                {"metric_version": version, "budget_type": kind, "records": len(metrics),
                 "mean_source_recall_ceiling": sum(m["source_recall_ceiling"] for m in metrics) / len(metrics),
                 "normalized_recall_records": sum(m["budget_normalized_source_recall"] is not None for m in metrics),
                 "mean_budget_normalized_source_recall": (
                     sum(m["budget_normalized_source_recall"] for m in metrics if m["budget_normalized_source_recall"] is not None)
                     / sum(m["budget_normalized_source_recall"] is not None for m in metrics)
                     if any(m["budget_normalized_source_recall"] is not None for m in metrics) else None)}
                for (version, kind), metrics in sorted(budget_groups.items())
            ]
        coverage = [item["claim_coverage"]["required_claim_coverage"] for item in items
                    if item.get("claim_coverage", {}).get("required_claim_coverage") is not None]
        if coverage:
            summary[method]["required_claim_coverage"] = {
                "records": len(coverage), "mean": sum(coverage) / len(coverage),
                "basis": "union of structured claims in annotated supporting passages"}
    return summary
