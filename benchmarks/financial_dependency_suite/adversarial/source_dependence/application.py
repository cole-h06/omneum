from ...application_comparison import (
    LLM_SELECTORS,
    application_record,
    generate_answer,
    select_bge,
    select_braid,
    select_cohere,
    select_llm_safe,
    select_vector,
    warm_local_models,
)
from ...answer_scoring import score_money_answer
from ...observations import build_observations, source_ids
from ...run_suite import estimator_config
from .cases import source_dependence
from .run_benchmark import build_judge_inputs


QUERY = "What was Arm Holdings' total revenue for fiscal 2023?"
CORRECT_VALUE = 2_679_000_000
FALSE_VALUE = 3_200_000_000
TOP_N = 3

GENERATOR_PROVIDER = "anthropic"
GENERATOR_MODEL = "claude-sonnet-5"


def case_data():
    case = source_dependence()

    observations = (
        build_observations("arm_ipo_2023_revenue")[:3]
        + case["observations"]
    )

    ids = {
        **source_ids("arm_ipo_2023_revenue"),
        **case["source_ids"],
    }

    candidates = build_judge_inputs(case)

    return candidates, observations, ids


def result_record(selection, generation):
    score = score_money_answer(
        generation["text"],
        correct=CORRECT_VALUE,
        false=FALSE_VALUE,
    )

    return application_record(
        selection,
        generation,
        score,
    )


async def finish(selection):
    generation = await generate_answer(
        QUERY,
        selection["selected"],
        provider=GENERATOR_PROVIDER,
        model=GENERATOR_MODEL,
    )

    return result_record(selection, generation)


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

    results["cohere"] = await finish(
        select_cohere(
            QUERY,
            candidates,
            top_n=TOP_N,
        )
    )

    results["braid"] = await finish(
        await select_braid(
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
        "benchmark": "source_dependence",
        "query": QUERY,
        "context_budget": TOP_N,
        "generator": GENERATOR_MODEL,
        "methods": results,
    }


def summary(trials):
    methods = {}

    for name in trials[0]["methods"]:
        runs = [
            trial["methods"][name]
            for trial in trials
        ]

        completed = [
            run
            for run in runs
            if run["answer_score"] != "selection_failure"
        ]

        methods[name] = {
            "trials": len(runs),
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
            "mean_selection_latency_seconds": (
                sum(
                    run["selection"]["latency_seconds"]
                    for run in runs
                ) / len(runs)
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
                    for run in completed
                ) / len(completed)
                if completed
                else None
            ),
            "mean_end_to_end_latency_seconds": (
                sum(
                    run["end_to_end_latency_seconds"]
                    for run in completed
                ) / len(completed)
                if completed
                else None
            ),
            "mean_selector_input_tokens": (
                sum(
                    run["selection"].get("input_tokens") or 0
                    for run in runs
                ) / len(runs)
            ),
            "mean_selector_output_tokens": (
                sum(
                    run["selection"].get("output_tokens") or 0
                    for run in runs
                ) / len(runs)
            ),
            "mean_generation_input_tokens": (
                sum(
                    run["generation"]["input_tokens"]
                    for run in completed
                ) / len(completed)
                if completed
                else None
            ),
            "mean_generation_output_tokens": (
                sum(
                    run["generation"]["output_tokens"]
                    for run in completed
                ) / len(completed)
                if completed
                else None
            ),
        }

    return {
        "benchmark": "source_dependence",
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
        "benchmarks/financial_dependency_suite/results/"
        "adversarial/source_dependence/application"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    run_id = datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )

    trials_path = output_dir / f"{run_id}.jsonl"
    summary_path = output_dir / f"{run_id}.summary.json"

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

    print(json.dumps(report, indent=2))
    print(f"\nTrials: {trials_path}")
    print(f"Summary: {summary_path}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
