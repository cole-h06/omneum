from ...application_comparison import (
    LLM_SELECTORS,
    application_record,
    generate_answer_safe,
    select_bge,
    select_omneum_reranked,
    select_cohere_safe,
    select_llm_safe,
    select_vector,
    warm_local_models,
)
from ...answer_scoring import score_value_answer
from ...config import estimator_config
from .cases import dependent_stale_data
from ...reproducibility import manifest, write_manifest
from ...clients import DEFAULT_MODELS


QUERY = "What is the current retention period for payments-api?"
CORRECT_VALUE = 90
FALSE_VALUE = 30
TOP_N = 3

GENERATOR_PROVIDER = "anthropic"
GENERATOR_MODEL = DEFAULT_MODELS[GENERATOR_PROVIDER]


def case_data():
    case = dependent_stale_data()

    return (
        case["documents"],
        case["observations"],
        case["source_ids"],
    )


def result_record(selection, generation):
    score = score_value_answer(
        generation["text"],
        correct=CORRECT_VALUE,
        false=FALSE_VALUE,
        unit="days",
    )

    return application_record(
        selection,
        generation,
        score,
    )


async def finish(selection):
    result = await generate_answer_safe(
        QUERY,
        selection["selected"],
        provider=GENERATOR_PROVIDER,
        model=GENERATOR_MODEL,
    )

    if result["failure"] is not None:
        failure = result["failure"]
        failure["selection"] = selection
        return failure

    return result_record(selection, result["generation"])


async def run():
    candidates, observations, ids = case_data()

    results = {}

    results["vector"] = await finish(
        select_vector(
            QUERY,
            candidates,
            top_n=TOP_N,
        )
    )

    results["bge"] = await finish(
        select_bge(
            QUERY,
            candidates,
            top_n=TOP_N,
        )
    )

    cohere = select_cohere_safe(
        QUERY,
        candidates,
        top_n=TOP_N,
    )

    if cohere["failure"] is not None:
        results["cohere"] = cohere["failure"]
    else:
        results["cohere"] = await finish(cohere["selection"])

    results["omneum"] = await finish(
        await select_omneum_reranked(
            QUERY,
            candidates,
            observations,
            ids,
            estimator=estimator_config(),
            top_n=TOP_N,
        )
    )

    for provider, model in LLM_SELECTORS:
        key = f"llm_{provider}"

        result = await select_llm_safe(
            QUERY,
            candidates,
            provider=provider,
            model=model,
            top_n=TOP_N,
        )

        if result["failure"] is not None:
            results[key] = result["failure"]
            continue

        results[key] = await finish(result["selection"])

    return {
        "benchmark": "data_staleness",
        "query": QUERY,
        "context_budget": TOP_N,
        "generator": GENERATOR_MODEL,
        "methods": results,
    }


def summary(trials):
    methods = {}

    for name in trials[0]["methods"]:
        runs = [trial["methods"][name] for trial in trials]
        evaluable = [
            run
            for run in runs
            if run["answer_score"] not in {
                "selection_failure",
                "generation_failure",
            }
        ]

        methods[name] = {
            "attempted_trials": len(runs),
            "evaluable_trials": len(evaluable),
            "correct": sum(
                run["answer_score"] == "correct"
                for run in runs
            ),
            "false": sum(
                run["answer_score"] == "false"
                for run in runs
            ),
            "ambiguous": sum(
                run["answer_score"] == "ambiguous"
                for run in runs
            ),
            "unscored": sum(
                run["answer_score"] == "unscored"
                for run in runs
            ),
            "selection_failures": sum(
                run["answer_score"] == "selection_failure"
                for run in runs
            ),
            "generation_failures": sum(
                run["answer_score"] == "generation_failure"
                for run in runs
            ),
            "mean_selection_latency_seconds": (
                sum(
                    run["selection"]["latency_seconds"]
                    for run in runs
                    if run["selection"]["latency_seconds"] is not None
                ) / sum(
                    run["selection"]["latency_seconds"] is not None
                    for run in runs
                )
                if any(
                    run["selection"]["latency_seconds"] is not None
                    for run in runs
                )
                else None
            ),
            "mean_evaluation_latency_seconds": (
                sum(
                    run["selection"]["evaluation_latency_seconds"]
                    for run in runs
                    if run["selection"].get("evaluation_latency_seconds")
                    is not None
                ) / sum(
                    run["selection"].get("evaluation_latency_seconds")
                    is not None
                    for run in runs
                )
                if any(
                    run["selection"].get("evaluation_latency_seconds")
                    is not None
                    for run in runs
                )
                else None
            ),
            "mean_cold_integration_latency_seconds": (
                sum(
                    run["selection"]["cold_integration_latency_seconds"]
                    for run in runs
                    if run["selection"].get(
                        "cold_integration_latency_seconds"
                    ) is not None
                ) / sum(
                    run["selection"].get(
                        "cold_integration_latency_seconds"
                    ) is not None
                    for run in runs
                )
                if any(
                    run["selection"].get(
                        "cold_integration_latency_seconds"
                    ) is not None
                    for run in runs
                )
                else None
            ),
            "mean_generation_latency_seconds": (
                sum(
                    run["generation"]["latency_seconds"]
                    for run in evaluable
                ) / len(evaluable)
                if evaluable
                else None
            ),
            "mean_end_to_end_latency_seconds": (
                sum(
                    run["end_to_end_latency_seconds"]
                    for run in evaluable
                ) / len(evaluable)
                if evaluable
                else None
            ),
            "mean_selector_input_tokens": (
                sum(
                    run["selection"]["input_tokens"]
                    for run in runs
                    if run["selection"].get("input_tokens") is not None
                ) / sum(
                    run["selection"].get("input_tokens") is not None
                    for run in runs
                )
                if any(
                    run["selection"].get("input_tokens") is not None
                    for run in runs
                )
                else None
            ),
            "mean_selector_output_tokens": (
                sum(
                    run["selection"]["output_tokens"]
                    for run in runs
                    if run["selection"].get("output_tokens") is not None
                ) / sum(
                    run["selection"].get("output_tokens") is not None
                    for run in runs
                )
                if any(
                    run["selection"].get("output_tokens") is not None
                    for run in runs
                )
                else None
            ),
            "mean_generation_input_tokens": (
                sum(
                    run["generation"]["input_tokens"]
                    for run in evaluable
                ) / len(evaluable)
                if evaluable
                else None
            ),
            "mean_generation_output_tokens": (
                sum(
                    run["generation"]["output_tokens"]
                    for run in evaluable
                ) / len(evaluable)
                if evaluable
                else None
            ),
        }

    return {
        "benchmark": "data_staleness",
        "trial_count": len(trials),
        "context_budget": TOP_N,
        "generator": GENERATOR_MODEL,
        "methods": methods,
    }


async def main():
    import argparse
    import json
    from datetime import datetime, timezone
    from pathlib import Path

    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=1)
    args = parser.parse_args()

    if args.trials < 1:
        parser.error("--trials must be at least 1")

    output_dir = Path(
        "benchmarks/context_selection/results/"
        "adversarial/data_staleness/application"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    run_id = datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )

    trials_path = output_dir / f"{run_id}.jsonl"
    summary_path = output_dir / f"{run_id}.summary.json"
    manifest_path = output_dir / f"{run_id}.manifest.json"

    candidates, _, _ = case_data()
    warm_local_models(QUERY, candidates)

    trials = []

    with trials_path.open("w") as handle:
        for number in range(1, args.trials + 1):
            print(f"Running trial {number}/{args.trials}...")

            trial = await run()
            trial["trial"] = number
            trials.append(trial)

            handle.write(json.dumps(trial) + "\n")
            handle.flush()

    report = summary(trials)

    summary_path.write_text(
        json.dumps(report, indent=2) + "\n"
    )

    run_manifest = manifest(
        benchmark="data_staleness",
        track="application",
        trials=args.trials,
        context_budget=TOP_N,
        models={
            "vector": "all-MiniLM-L6-v2",
            "bge": "BAAI/bge-reranker-v2-m3",
            "cohere": "rerank-v4.0-pro",
            "anthropic": DEFAULT_MODELS["anthropic"],
            "openai": DEFAULT_MODELS["openai"],
            "google": DEFAULT_MODELS["google"],
            "generator": GENERATOR_MODEL,
        },
        inputs=[
            Path(__file__),
            Path(__file__).with_name("cases.py"),
        ],
        identifier=run_id,
    )
    write_manifest(manifest_path, run_manifest)

    print(json.dumps(report, indent=2))
    print(f"\nTrials: {trials_path}")
    print(f"Summary: {summary_path}")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
