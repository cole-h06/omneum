import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from .cases import dependent_stale_data, independent_stale_data
from ..comparison import (
    evaluate_llm_judges,
    mean_or_none,
    summarize_llm_judges,
)
from ...braid_rag import evaluate_context, map_observations, select_context
from ...config import estimator_config
from ...reproducibility import manifest, write_manifest


OUTPUT_DIR = Path(
    "benchmarks/financial_dependency_suite/results/adversarial/"
    "data_staleness"
)

STALE_VALUE = 30
CURRENT_VALUE = 90

DEPENDENT_RELATIONSHIPS = {
    ("stale_copy_a", "stale_origin"),
    ("stale_copy_b", "stale_copy_a"),
}
INDEPENDENT_RELATIONSHIPS = set()


def mapped(case):
    return map_observations(
        case["documents"],
        case["observations"],
        case["source_ids"],
    )


def build_judge_inputs(case):
    ids = case["source_ids"]
    documents = {
        item["source"]: item["text"]
        for item in case["documents"]
    }

    results = []

    for observation in case["observations"]:
        source_id = ids[observation.source]

        upstream_ids = [
            ids[source]
            for reference in observation.upstream_sources
            for source in ids
            if (
                source.kind == reference.kind
                and source.identifier == reference.identifier
            )
        ]

        cited_ids = [
            ids[source]
            for reference in observation.cited_sources
            for source in ids
            if (
                source.kind == reference.kind
                and source.identifier == reference.identifier
            )
        ]

        results.append({
            "source": source_id,
            "score": 0.0,
            "text": documents[source_id],
            "metadata": {
                "observed_at": observation.observed_at.isoformat(),
                "source_modified_at":
                    observation.source_modified_at.isoformat(),
                "upstream_sources": upstream_ids,
                "cited_sources": cited_ids,
                "parent_assertion_ids":
                    list(observation.parent_assertion_ids),
            },
        })

    return results


def claim_record(claim):
    return {
        "value": claim.claim.value,
        "support": claim.support,
        "estimated_independent_support_count":
            claim.estimated_independent_support_count,
        "is_attribute_max_support":
            claim.is_attribute_max_support,
        "supporting_sources": [
            {
                "source": supporter.source.identifier,
                "contribution": supporter.contribution,
            }
            for supporter in claim.supporting_sources
        ],
    }


def selected_record(selected):
    return [
        {
            "source": item["retrieved"]["source"],
            "claim_value": item["claim"].value,
            "claim_support": item["claim_support"],
            "braid_contribution": item["braid_contribution"],
        }
        for item in selected
    ]


async def evaluate(case):
    case_mapped = mapped(case)

    started = perf_counter()

    result = await evaluate_context(
        case_mapped,
        estimator=estimator_config(),
    )

    selected = select_context(
        case_mapped,
        result,
        top_n=4,
    )

    latency_seconds = perf_counter() - started

    return result, selected, latency_seconds


async def run_trial(trial_number):
    dependent_case = dependent_stale_data()
    independent_case = independent_stale_data()

    (
        dependent_result,
        dependent_selected,
        dependent_braid_latency,
    ) = await evaluate(dependent_case)

    (
        independent_result,
        independent_selected,
        independent_braid_latency,
    ) = await evaluate(independent_case)

    query = "What is the current retention period for payments-api?"

    dependent_llm_judges = await evaluate_llm_judges(
        query=query,
        results=build_judge_inputs(dependent_case),
        expected_relationships=DEPENDENT_RELATIONSHIPS,
        include_text=False,
    )

    independent_llm_judges = await evaluate_llm_judges(
        query=query,
        results=build_judge_inputs(independent_case),
        expected_relationships=INDEPENDENT_RELATIONSHIPS,
        include_text=False,
    )

    dependent = {
        claim.claim.value: claim
        for claim in dependent_result.claim_support
    }
    independent = {
        claim.claim.value: claim
        for claim in independent_result.claim_support
    }

    return {
        "benchmark": "data_staleness",
        "trial": trial_number,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "ground_truth": dependent_case["ground_truth"],
        "stale_value": STALE_VALUE,
        "current_value": CURRENT_VALUE,
        "dependent_treatment": {
            "braid_latency_seconds": dependent_braid_latency,
            "claims": [
                claim_record(claim)
                for claim in dependent_result.claim_support
            ],
            "selected_context":
                selected_record(dependent_selected),
            "llm_judges": dependent_llm_judges,
        },
        "independent_control": {
            "braid_latency_seconds": independent_braid_latency,
            "claims": [
                claim_record(claim)
                for claim in independent_result.claim_support
            ],
            "selected_context":
                selected_record(independent_selected),
            "llm_judges": independent_llm_judges,
        },
        "checks": {
            "dependency_reduces_stale_independent_support":
                dependent[STALE_VALUE]
                .estimated_independent_support_count
                < independent[STALE_VALUE]
                .estimated_independent_support_count,
            "current_beats_stale_when_stale_is_dependent":
                dependent[CURRENT_VALUE].support
                > dependent[STALE_VALUE].support,
            "current_is_only_treatment_winner":
                dependent[CURRENT_VALUE].is_attribute_max_support
                and not dependent[STALE_VALUE].is_attribute_max_support,
            "control_is_tied":
                abs(
                    independent[STALE_VALUE].support
                    - independent[CURRENT_VALUE].support
                ) < 1e-9,
            "both_control_claims_are_winners":
                independent[STALE_VALUE].is_attribute_max_support
                and independent[CURRENT_VALUE].is_attribute_max_support,
        },
    }


def summarize_condition(trials, condition):
    braid_latencies = [
        trial[condition]["braid_latency_seconds"]
        for trial in trials
    ]

    return {
        "braid": {
            "trials": len(trials),
            "mean_latency_seconds":
                mean_or_none(braid_latencies),
        },
        "llm_judges":
            summarize_llm_judges(trials, condition),
    }


def build_summary(trials):
    return {
        "benchmark": "data_staleness",
        "trial_count": len(trials),
        "generated_at_utc":
            datetime.now(timezone.utc).isoformat(),
        "dependent_treatment":
            summarize_condition(trials, "dependent_treatment"),
        "independent_control":
            summarize_condition(trials, "independent_control"),
        "braid_checks": {
            key: all(
                trial["checks"][key]
                for trial in trials
            )
            for key in trials[0]["checks"]
        },
    }


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=1)
    args = parser.parse_args()

    if args.trials < 1:
        parser.error("--trials must be at least 1")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    trials_output = OUTPUT_DIR / f"{run_id}.jsonl"
    summary_output = OUTPUT_DIR / f"{run_id}.summary.json"
    manifest_output = OUTPUT_DIR / f"{run_id}.manifest.json"
    trials = []

    with trials_output.open("x") as handle:
        for trial_number in range(1, args.trials + 1):
            print(f"Running trial {trial_number}/{args.trials}...")

            trial = await run_trial(trial_number)
            trials.append(trial)

            handle.write(json.dumps(trial) + "\n")
            handle.flush()

    summary = build_summary(trials)

    summary_output.write_text(
        json.dumps(summary, indent=2) + "\n"
    )

    run_manifest = manifest(
        benchmark="data_staleness",
        track="structural",
        trials=args.trials,
        inputs=[
            Path(__file__),
            Path(__file__).with_name("cases.py"),
        ],
        identifier=run_id,
    )
    write_manifest(manifest_output, run_manifest)

    print(json.dumps(summary, indent=2))
    print(f"\nTrials: {trials_output}")
    print(f"Summary: {summary_output}")
    print(f"Manifest: {manifest_output}")


if __name__ == "__main__":
    asyncio.run(main())
