"""Offline, read-only paired latency analysis. No benchmark/provider imports."""

import argparse
import json
import math
from pathlib import Path


DEFAULT_RESULTS = Path(__file__).parent / "results/20261008T014713Z/results.jsonl"
METHODS = ("cohere", "cohere_omneum")


def seconds(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0)


def close(a, b):
    return seconds(a) and seconds(b) and math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)


def percentile(values, q):
    """Linear interpolation at (n - 1) * q, matching the historical summary."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def stats(values, total, basis):
    valid = [value for value in values if seconds(value)]
    return {"n": len(valid), "total": total, "basis": basis,
            "p50": percentile(valid, .5), "p95": percentile(valid, .95)}


def read_jsonl(path):
    with Path(path).open() as stream:
        return [json.loads(line) for line in stream if line.strip()]


def analyze(rows, responses=(), *, expected_cases=24):
    """Reject unpaired identities; flag incompatible clocks without inventing values."""
    grouped = {method: {} for method in METHODS}
    for row in rows:
        method = row.get("method")
        if method not in grouped:
            continue
        key = (row["case_id"], row["trial"])
        if key in grouped[method]:
            raise ValueError(f"duplicate {method} case/trial: {key}")
        grouped[method][key] = row
    keys = set(grouped["cohere"])
    if keys != set(grouped["cohere_omneum"]):
        raise ValueError("Cohere and Cohere + Omneum must have identical case/trial sets")
    if len(keys) != expected_cases or len({key[0] for key in keys}) != expected_cases:
        raise ValueError(f"expected {expected_cases} distinct cases with one paired trial each")

    cached = {}
    for response in responses:
        key = response["request_hash"]
        value = response["selection"]["latency_seconds"]
        if key in cached and not close(value, cached[key]):
            raise ValueError(f"conflicting shared response timings: {key}")
        if not seconds(value):
            raise ValueError(f"invalid shared response timing: {key}")
        cached[key] = value

    warnings = []
    samples = {method: [] for method in METHODS}
    for key in sorted(keys):
        pair = [grouped[method][key] for method in METHODS]
        selections = [row.get("selection") or {} for row in pair]
        hashes = [selection.get("cohere_request_hash") for selection in selections]
        if not hashes[0] or hashes[0] != hashes[1]:
            raise ValueError(f"shared Cohere request identity mismatch: {key}")
        for field in ("relevance_model", "relevance_depth", "relevance_selected"):
            if selections[0].get(field) != selections[1].get(field):
                raise ValueError(f"shared Cohere {field} mismatch: {key}")
        reranks = [s.get("cohere_response_latency_seconds") for s in selections]
        if not close(*reranks):
            raise ValueError(f"shared Cohere response timing mismatch: {key}")
        rerank = reranks[0]
        if cached and (hashes[0] not in cached or not close(rerank, cached[hashes[0]])):
            raise ValueError(f"shared response file disagrees with results: {key}")

        for method, row, selection in zip(METHODS, pair, selections):
            label = f"{key[0]}/{key[1]} {method}"
            sample = {"case_id": key[0], "trial": key[1], "reranking": rerank,
                      "cache_hit": selection.get("cohere_cache_hit")}
            work = selection.get("cohere_latency_seconds")
            hit = sample["cache_hit"]
            coherent = isinstance(hit, bool) and close(work, 0 if hit else rerank)
            omneum = 0 if method == "cohere" else selection.get("omneum_latency_seconds")
            cold = selection.get("cold_integration_latency_seconds")
            evaluation = selection.get("evaluation_latency_seconds")
            if method == "cohere_omneum":
                sample["cold_integration"] = cold if seconds(cold) else None
                sample["evaluation"] = evaluation if seconds(evaluation) else None
                if not close(cold, omneum):
                    warnings.append(f"{label}: cold integration and Omneum latency cannot be reconciled")
                    coherent = False
                if seconds(cold) and seconds(evaluation) and evaluation <= cold:
                    sample["cold_overhead"] = cold - evaluation
                else:
                    sample["cold_overhead"] = None
                    warnings.append(f"{label}: cold overhead unavailable; evaluation missing/invalid or exceeds integration")
                if not seconds(evaluation):
                    warnings.append(f"{label}: evaluation timing unavailable")
            selection_time = selection.get("latency_seconds")
            if not (seconds(work) and seconds(omneum) and close(selection_time, work + omneum)):
                coherent = False
            if not coherent:
                warnings.append(f"{label}: selection/cache/component timings cannot be fairly reconciled")
            generation = (row.get("generation") or {}).get("latency_seconds")
            sample["generation"] = generation if seconds(generation) else None
            recorded = row.get("end_to_end_latency_seconds")
            e2e_coherent = (seconds(selection_time) and seconds(generation)
                            and close(recorded, selection_time + generation))
            if not e2e_coherent:
                warnings.append(f"{label}: recorded end-to-end does not reconcile with selection + generation")
            sample["recorded_end_to_end"] = recorded if seconds(recorded) else None
            # Replace the run's Cohere work with the shared timing once. The
            # evaluation is nested in Omneum integration and must not be added.
            sample["corrected_selection"] = rerank + omneum if coherent else None
            sample["corrected_end_to_end"] = (
                rerank + omneum + generation if coherent and e2e_coherent else None
            )
            samples[method].append(sample)

    bases = {
        "reranking": "measured shared Cohere response; reused for cached rows",
        "evaluation": "measured SDK evaluation call; includes transport and validation, not pure inference",
        "cold_integration": "measured cold Omneum integration; includes evaluation",
        "cold_overhead": "estimated cold integration minus evaluation; not isolated startup",
        "generation": "measured generation call, method-specific",
        "recorded_end_to_end": "recorded component sum; cache-dependent, not wall-clock measurement",
        "corrected_selection": "reconstructed reranking + cold Omneum integration (if applicable)",
        "corrected_end_to_end": "reconstructed reranking + cold Omneum integration + generation",
    }
    metrics = {method: {name: stats([s.get(name) for s in values], len(keys), basis)
                        for name, basis in bases.items()} for method, values in samples.items()}
    notes = [
        "Percentiles: linear interpolation at (n - 1) * q, in seconds; N/A is unavailable, not zero.",
        "24 shared response timings are reused across methods, not 48 independent reranks."
        if len(keys) == 24 else f"{len(keys)} shared timings are reused across methods.",
        "Cache correction replaces Cohere work once per case; evaluation is already inside cold integration.",
        "Cold overhead includes deployment, connection, teardown, mapping and selection; isolated startup and warm-start latency are unavailable.",
        "Cohere HTTP 429 retries/backoff can inflate measured reranking and corrected end-to-end tails. Retry counts/statuses/durations are absent; no retry-free estimate or attribution is possible.",
        "Recorded end-to-end is a component sum, excluding work outside the component timers (including Cohere client construction); true wall-clock end-to-end is unavailable.",
        "Generation timings come from separate answers; end-to-end differences do not isolate Omneum overhead.",
    ]
    return {"paired_cases": len(keys), "shared_response_file_verified": bool(cached),
            "metrics": metrics, "samples": samples, "warnings": warnings, "notes": notes}


def format_table(report):
    lines = [f"Paired cases: {report['paired_cases']}; seconds (P50 / P95)",
             "Metric / basis                    Cohere               Cohere + Omneum"]
    names = [("reranking", "Reranking [measured shared]"),
             ("evaluation", "Omneum evaluation [measured]"),
             ("cold_integration", "Omneum cold total [measured]"),
             ("cold_overhead", "Cold overhead [estimate]"),
             ("generation", "Generation [measured]"),
             ("corrected_selection", "Selection [reconstructed]"),
             ("recorded_end_to_end", "E2E recorded [component sum]"),
             ("corrected_end_to_end", "E2E corrected [reconstructed]")]
    for name, label in names:
        cells = []
        for method in METHODS:
            metric = report["metrics"][method][name]
            cells.append("N/A" if not metric["n"] else
                         f"{metric['p50']:.4f} / {metric['p95']:.4f} ({metric['n']}/{metric['total']})")
        lines.append(f"{label:33} {cells[0]:21} {cells[1]}")
    lines.extend(f"Note: {note}" for note in report["notes"])
    lines.extend(f"WARNING: {warning}" for warning in report["warnings"])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", nargs="?", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--expected-cases", type=int, default=24)
    parser.add_argument("--json", action="store_true", help="print auditable per-case values to stdout")
    args = parser.parse_args()
    cache = args.results.with_name("cohere_responses.jsonl")
    try:
        report = analyze(read_jsonl(args.results), read_jsonl(cache) if cache.exists() else (),
                         expected_cases=args.expected_cases)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    if not cache.exists():
        report["warnings"].append("shared response file unavailable; only paired result timings verified")
    print(json.dumps(report, indent=2, allow_nan=False) if args.json else format_table(report))


if __name__ == "__main__":
    main()
