"""Aggregate frozen question-support runs for a promotion review."""
import csv, json, random, statistics
from pathlib import Path

ROOT = Path(__file__).parent / "results"
OUT = ROOT / "question-support-qualification-v3"
BUDGETS = (64, 96, 128, 160, 192, 256)

def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]

def selected(path, method, dataset):
    return [r for r in rows(path) if r.get("method") == method and r.get("dataset", "original") == dataset]

def percentile(values, p):
    vals = sorted(values)
    if not vals:
        return None
    index = (len(vals) - 1) * p
    lo = int(index); hi = min(lo + 1, len(vals) - 1)
    return vals[lo] + (vals[hi] - vals[lo]) * (index - lo)

def metrics(group):
    out = {"n": len(group)}
    for name, key in (("answer_accuracy", "value_correct"), ("strict_json_accuracy", "strict_correct"),
                      ("selection_precision", "selection_precision"), ("selection_recall", "selection_recall"),
                      ("critical_evidence_retention", "critical_evidence_retention"),
                      ("qualification_retention", "qualification_retention"),
                      ("independent_evidence_coverage", "independent_evidence_coverage"),
                      ("actual_context_tokens", "actual_context_tokens")):
        vals = [float(r[key]) for r in group if r.get(key) is not None]
        out[name] = statistics.mean(vals) if vals else None
    out["dependent_duplicate_selection"] = sum(float(r.get("dependent_duplicate_selection") or 0) for r in group)
    out["selection_latency_p50_ms"] = percentile([r["selection_latency_ms"] for r in group], .5)
    out["selection_latency_p95_ms"] = percentile([r["selection_latency_ms"] for r in group], .95)
    out["generation_latency"] = {}
    for origin in ("fresh", "matched_existing", "run_cache"):
        g = [r for r in group if r.get("generation_origin") == origin]
        out["generation_latency"][origin] = {"n": len(g),
            "p50_ms": percentile([r["end_to_end_latency_ms"] for r in g], .5),
            "p95_ms": percentile([r["end_to_end_latency_ms"] for r in g], .95)}
    return out

def paired(candidate, baseline):
    a = {(r["case_id"], r["budget"], r["trial"]): int(r["value_correct"]) for r in candidate}
    b = {(r["case_id"], r["budget"], r["trial"]): int(r["value_correct"]) for r in baseline}
    keys = sorted(a.keys() & b.keys())
    by_case = {}
    for key in keys:
        by_case.setdefault(key[0], []).append(a[key] - b[key])
    vals = [statistics.mean(v) for v in by_case.values()]
    rng = random.Random(6382)
    boots = [statistics.mean(rng.choices(vals, k=len(vals))) for _ in range(10000)]
    return {"pairs": len(keys), "cases": len(vals),
        "wins": sum(a[k] > b[k] for k in keys), "losses": sum(a[k] < b[k] for k in keys),
        "ties": sum(a[k] == b[k] for k in keys), "mean_accuracy_difference": statistics.mean(vals),
        "ci95_case_cluster_bootstrap": [percentile(boots, .025), percentile(boots, .975)]}

def main(output):
    from .execution_safety import require_new_output
    output = Path(output)
    require_new_output(output)
    result = {}
    flat = []
    for dataset in ("original", "independent"):
        if dataset == "original":
            historical = ROOT / "question-support-qwen-v1/results.jsonl"
        else:
            historical = ROOT / "question-support-independent-v1/results.jsonl"
        base_rows = rows(historical)
        paths = {
            "production_default": (base_rows, "production_default"),
            "previous_question_weighted": (base_rows, "question_support"),
        }
        corrected_rows = rows(ROOT / "question-support-qualification-v1/corrected-qwen-v1/results.jsonl")
        final_rows = rows(OUT / "final-qwen-v1/results.jsonl")
        paths["current_corrected"] = (corrected_rows, "question_support_field_relevance")
        paths["final_question_weighted"] = (final_rows, "question_support_final_default")
        ds_result = {}
        method_rows = {}
        for label, (source_rows, method) in paths.items():
            selected_rows = [r for r in source_rows if r.get("method") == method and r.get("dataset", dataset) == dataset]
            method_rows[label] = selected_rows
            ds_result[label] = {"overall": metrics(selected_rows),
                "by_budget": {str(b): metrics([r for r in selected_rows if r["budget"] == b]) for b in BUDGETS}}
            for budget in BUDGETS:
                flat.append({"dataset": dataset, "method": label, "budget": budget,
                             **metrics([r for r in selected_rows if r["budget"] == budget])})
        ds_result["paired_final_vs"] = {name: paired(method_rows["final_question_weighted"], method_rows[name])
            for name in ("production_default", "previous_question_weighted", "current_corrected")}
        result[dataset] = ds_result

    output.mkdir(parents=True, exist_ok=False)
    (output / "promotion_review.json").write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    with (output / "promotion_by_budget.csv").open("w", newline="") as stream:
        fields = list(dict.fromkeys(key for row in flat for key in row))
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader(); writer.writerows(flat)
    print(json.dumps({ds: {method: value["overall"] for method, value in block.items() if method != "paired_final_vs"}
                      | {"paired_final_vs": block["paired_final_vs"]} for ds, block in result.items()}, indent=2))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    main(parser.parse_args().output)
