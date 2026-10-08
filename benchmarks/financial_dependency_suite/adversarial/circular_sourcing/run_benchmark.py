import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from .cases import (
    circular_sources,
    acyclic_dependency_chain,
    independent_sources_control,
)
from ..comparison import (
    evaluate_llm_judges,
    mean_or_none,
    summarize_llm_judges,
)
from ...omneum_rag import evaluate_context, map_observations, select_context
from ...config import estimator_config
from ...reproducibility import manifest, write_manifest


OUTPUT_DIR = Path(
    "benchmarks/financial_dependency_suite/results/adversarial/"
    "circular_sourcing"
)

DEPENDENT_VALUE = 30
INDEPENDENT_VALUE = 60

CIRCULAR_RELATIONSHIPS = {
    ("circular_a", "circular_c"),
    ("circular_b", "circular_a"),
    ("circular_c", "circular_b"),
}

ACYCLIC_RELATIONSHIPS = {
    ("circular_b", "circular_a"),
    ("circular_c", "circular_b"),
}

CONTROL_RELATIONSHIPS = set()


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
                    list(observation.parent_observation_ids),
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
            "omneum_contribution": item["omneum_contribution"],
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
        QUERY,
        case_mapped,
        result,
        top_n=4,
    )

    latency_seconds = perf_counter() - started

    return result, selected, latency_seconds


def by_value(result):
    return {
        claim.claim.value: claim
        for claim in result.claim_support
    }


async def evaluate_condition(case, expected_relationships):
    result, selected, omneum_latency = await evaluate(case)

    llm_judges = await evaluate_llm_judges(
        query="What is the payments-api request timeout?",
        results=build_judge_inputs(case),
        expected_relationships=expected_relationships,
        include_text=False,
    )

    return result, selected, omneum_latency, llm_judges


async def run_trial(trial_number):
    circular_case = circular_sources()
    acyclic_case = acyclic_dependency_chain()
    control_case = independent_sources_control()

    (
        circular_result,
        circular_selected,
        circular_latency,
        circular_llm,
    ) = await evaluate_condition(
        circular_case,
        CIRCULAR_RELATIONSHIPS,
    )

    (
        acyclic_result,
        acyclic_selected,
        acyclic_latency,
        acyclic_llm,
    ) = await evaluate_condition(
        acyclic_case,
        ACYCLIC_RELATIONSHIPS,
    )

    (
        control_result,
        control_selected,
        control_latency,
        control_llm,
    ) = await evaluate_condition(
        control_case,
        CONTROL_RELATIONSHIPS,
    )

    circular = by_value(circular_result)
    acyclic = by_value(acyclic_result)
    control = by_value(control_result)

    circular_effective = (
        circular[DEPENDENT_VALUE]
        .estimated_independent_support_count
    )
    acyclic_effective = (
        acyclic[DEPENDENT_VALUE]
        .estimated_independent_support_count
    )

    cycle_reduction = (
        1.0 - circular_effective / acyclic_effective
        if acyclic_effective
        else None
    )

    return {
        "benchmark": "circular_sourcing",
        "trial": trial_number,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "dependent_value": DEPENDENT_VALUE,
        "independent_value": INDEPENDENT_VALUE,
        "circular_treatment": {
            "omneum_latency_seconds": circular_latency,
            "claims": [
                claim_record(claim)
                for claim in circular_result.claim_support
            ],
            "selected_context":
                selected_record(circular_selected),
            "llm_judges": circular_llm,
        },
        "acyclic_chain_control": {
            "omneum_latency_seconds": acyclic_latency,
            "claims": [
                claim_record(claim)
                for claim in acyclic_result.claim_support
            ],
            "selected_context":
                selected_record(acyclic_selected),
            "llm_judges": acyclic_llm,
        },
        "no_relationship_control": {
            "omneum_latency_seconds": control_latency,
            "claims": [
                claim_record(claim)
                for claim in control_result.claim_support
            ],
            "selected_context":
                selected_record(control_selected),
            "llm_judges": control_llm,
        },
        "cycle_effect": {
            "circular_effective_independent_support":
                circular_effective,
            "acyclic_effective_independent_support":
                acyclic_effective,
            "relative_reduction_vs_acyclic_chain":
                cycle_reduction,
        },
        "checks": {
            "circular_support_is_discounted":
                circular[DEPENDENT_VALUE].support
                < circular[INDEPENDENT_VALUE].support,
            "cycle_reduces_effective_support_vs_acyclic_chain":
                circular_effective < acyclic_effective,
            "no_relationship_control_is_tied":
                abs(
                    control[DEPENDENT_VALUE].support
                    - control[INDEPENDENT_VALUE].support
                ) < 1e-9,
            "both_no_relationship_claims_are_winners":
                control[DEPENDENT_VALUE].is_attribute_max_support
                and control[INDEPENDENT_VALUE].is_attribute_max_support,
        },
    }


def summarize_condition(trials, condition):
    omneum_latencies = [
        trial[condition]["omneum_latency_seconds"]
        for trial in trials
    ]

    return {
        "omneum": {
            "trials": len(trials),
            "mean_latency_seconds":
                mean_or_none(omneum_latencies),
        },
        "llm_judges":
            summarize_llm_judges(trials, condition),
    }


def build_summary(trials):
    cycle_reductions = [
        trial["cycle_effect"]["relative_reduction_vs_acyclic_chain"]
        for trial in trials
        if trial["cycle_effect"]["relative_reduction_vs_acyclic_chain"]
        is not None
    ]

    return {
        "benchmark": "circular_sourcing",
        "trial_count": len(trials),
        "generated_at_utc":
            datetime.now(timezone.utc).isoformat(),
        "circular_treatment":
            summarize_condition(trials, "circular_treatment"),
        "acyclic_chain_control":
            summarize_condition(trials, "acyclic_chain_control"),
        "no_relationship_control":
            summarize_condition(trials, "no_relationship_control"),
        "mean_relative_cycle_reduction":
            mean_or_none(cycle_reductions),
        "omneum_checks": {
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
        benchmark="circular_sourcing",
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
