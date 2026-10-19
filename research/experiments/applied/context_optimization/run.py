import argparse
import asyncio
from dataclasses import asdict
from pathlib import Path
from statistics import mean
from time import perf_counter

from omneum import evaluate_context, reconstruct_context
from omneum.context_selection import claim_id, map_chunks, select_chunks, token_count

from benchmarks.context_evaluation.application_comparison import (
    generate_answer_safe,
    provider_error_diagnostics,
    select_bge,
)
from benchmarks.context_evaluation.config import estimator_config
from benchmarks.context_evaluation.heldout.aggregate import summarize
from benchmarks.context_evaluation.heldout.artifacts import checkpoint, write_json
from benchmarks.context_evaluation.heldout.checkpoint import implementation_hash
from benchmarks.context_evaluation.heldout.loader import application_candidates
from benchmarks.context_evaluation.heldout.run_benchmark import CASES_DIR, discover_cases
from benchmarks.context_evaluation.heldout.scoring import score_answer, score_selection
from benchmarks.context_evaluation.heldout.sdk_adapter import build_observations
from benchmarks.context_evaluation.reproducibility import manifest, sha256_file


METHODS = ("retrieval", "semantic", "omneum", "semantic_omneum")


def select_context(method, case, budget):
    if method not in METHODS:
        raise ValueError(f"unknown method: {method}")
    started = perf_counter()
    observations, _ = build_observations(case)
    chunks = [
        {"chunk_id": candidate.source_id, "raw_text": candidate.text,
         "claim_ids": [claim_id(observation.claim)]}
        for candidate, observation in zip(case.candidates, observations, strict=True)
    ]
    ranking = None
    if method in ("semantic", "semantic_omneum"):
        ranking = select_bge(
            case.question, application_candidates(case), top_n=len(chunks),
        )
        by_id = {chunk["chunk_id"]: chunk for chunk in chunks}
        chunks = [by_id[item["source"]] for item in ranking["selected"]]
    evaluation = None
    if method in ("omneum", "semantic_omneum"):
        evaluation = evaluate_context(observations, estimator=estimator_config())
        selection = reconstruct_context(evaluation, chunks, token_budget=budget)
    else:
        support = {identifier: 0.0 for chunk in chunks for identifier in chunk["claim_ids"]}
        selection = select_chunks(map_chunks(chunks, support), support, budget, "retrieval")

    selection["context_units"] = selection.pop("token_usage")
    selection["latency_seconds"] = perf_counter() - started
    selection["semantic_ranking"] = ranking
    selection["evaluation"] = None
    if evaluation is not None:
        selection["evaluation_latency_seconds"] = evaluation.evaluation_latency_ms / 1000
        selection["evaluation"] = {
            "claim_support": {claim_id(item.claim): item.support for item in evaluation.claim_support},
            "source_reliability": [
                {"kind": item.source.kind, "identifier": item.source.identifier,
                 "reliability": item.reliability}
                for item in evaluation.source_reliability
            ],
            "convergence": asdict(evaluation.convergence),
        }
    claims_by_chunk = {chunk["chunk_id"]: chunk["claim_ids"] for chunk in chunks}
    claims = [identifier for chunk in selection["chunks"]
              for identifier in claims_by_chunk[chunk["chunk_id"]]]
    selection["repeated_claim_fraction"] = 1 - len(set(claims)) / len(claims) if claims else 0.0
    return selection


async def run_case(case, truth, *, budget, provider, model, trial):
    if case.case_id != truth.case_id:
        raise ValueError("case/truth mismatch")
    records = []
    # Rotate method order between trials to reduce systematic service-order effects.
    offset = (trial - 1) % len(METHODS)
    for method in METHODS[offset:] + METHODS[:offset]:
        started = perf_counter()
        record = {"case_id": case.case_id, "domain": case.domain,
                  "method": method, "trial": trial}
        try:
            selection = select_context(method, case, budget)
        except Exception as exc:
            records.append({**record, "selected": [], "answer": None,
                            "answer_score": "selection_failure", "generation": None,
                            "failure_type": "selection_error",
                            "response_diagnostics": provider_error_diagnostics(exc),
                            "end_to_end_latency_seconds": perf_counter() - started})
            continue
        documents = [{"source": chunk["chunk_id"], "text": chunk["raw_text"]}
                     for chunk in selection["chunks"]]
        generator_context = "\n\n".join(f"Source: {item['source']}\n{item['text']}" for item in documents)
        # Both renderings have two header units; enforce the actual generator evidence budget.
        if token_count(generator_context) != selection["context_units"]:
            raise ValueError("selection and generator context budgets disagree")
        generated = await generate_answer_safe(case.question, documents, provider=provider, model=model)
        selected = selection["selected_chunk_ids"]
        generation = generated["generation"]
        result = generated["failure"] or {
            "answer": generation["text"], "answer_score": score_answer(generation["text"], truth),
        }
        records.append({**record, **result, "selected": selected,
                        "selection_score": score_selection(selected, truth),
                        "selection": selection, "generator_context": generator_context,
                        "generation": generation,
                        "end_to_end_latency_seconds": perf_counter() - started})
    return records


def aggregate(records):
    summary = summarize(records)
    for method, metrics in summary.items():
        selections = [record["selection"] for record in records
                      if record["method"] == method and record.get("selection") is not None]
        metrics["proxy_metrics"] = {
            name: mean(selection[name] for selection in selections) if selections else None
            for name in ("context_units", "repeated_claim_fraction")
        }
    return summary


async def run(output, *, budget=100, trials=1, case_ids=None, limit=None,
              provider="anthropic", model):
    if budget < 0 or trials < 1 or (limit is not None and limit < 1):
        raise ValueError("budget must be nonnegative; trials and limit must be positive")
    discovered = discover_cases(CASES_DIR)
    if case_ids:
        unknown = set(case_ids) - {case.case_id for _, _, case, _ in discovered}
        if unknown:
            raise ValueError(f"unknown case IDs: {sorted(unknown)}")
        discovered = [item for item in discovered if item[2].case_id in case_ids]
    if limit is not None:
        discovered = discovered[:limit]
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    metadata = manifest(
        benchmark="context_optimization_v1", track="heldout_token_budget",
        trials=trials, context_budget=budget,
        models={"generator_provider": provider, "generator": model,
                "semantic": "BAAI/bge-reranker-v2-m3"},
        inputs=[path for case_path, truth_path, _, _ in discovered for path in (case_path, truth_path)],
    )
    metadata.update({
        "methods": METHODS, "case_ids": [case.case_id for _, _, case, _ in discovered],
        "runtime_implementation_sha256": implementation_hash(),
        "experiment_sha256": sha256_file(__file__),
        "budget_unit": "unicode word/punctuation units including source labels; proxy, not model tokens",
        "generator_output_cap": 1024,
        "generator_parameters": "shared benchmark adapter defaults; no seed or temperature control",
        "semantic_omneum": "full BGE ordering followed by production coverage_support; BGE breaks equal marginal gains",
        "evaluator": "local production evaluate_context; structured observations only; no MCP transport",
        "latency_scope": "wall clock including local preparation and cold model loading; no warmup",
        "metrics": {
            "accuracy": "measured generated answer, required/forbidden-string scorer; unscored retained",
            "selection_recall": "proxy evidence coverage: labeled supporting-source recall",
            "repeated_claim_fraction": "proxy redundancy: 1 - distinct mapped claims / selected chunks; empty = 0",
            "context_units": "proxy evidence size; fixed prompt and question excluded",
            "generator_usage": "provider-reported input/output tokens, including prompt",
        },
    })
    write_json(output / "manifest.json", metadata)
    records = []
    checkpoint(output / "results.jsonl", records)
    for _, _, case, truth in discovered:
        for trial in range(1, trials + 1):
            batch = await run_case(case, truth, budget=budget, provider=provider, model=model, trial=trial)
            for record in batch:
                records.append(record)
                checkpoint(output / "results.jsonl", records)
            print(f"{case.case_id} trial={trial}: " + ", ".join(
                f"{record['method']}={record['answer_score']}" for record in batch), flush=True)
    write_json(output / "summary.json", aggregate(records))
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--budget", type=int, default=100)
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--case", action="append", dest="case_ids")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--provider", choices=("anthropic", "openai", "google"), default="anthropic")
    parser.add_argument("--model", required=True)
    arguments = parser.parse_args()
    print(asyncio.run(run(**vars(arguments))))


if __name__ == "__main__":
    main()
