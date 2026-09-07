import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from .cases import (
    source_dependence,
    independent_sources_control,
)
from ...braid_rag import (
    evaluate_context,
    map_observations,
    select_context,
)
from ..comparison import (
    evaluate_llm_judges,
    mean_or_none,
    summarize_llm_judges,
)
from ...naive_rag import load_documents
from ...observations import build_observations, source_ids
from ...config import estimator_config
from ...reproducibility import manifest, write_manifest


OUTPUT_DIR = Path(
    "benchmarks/financial_dependency_suite/results/adversarial/"
    "source_dependence"
)

CORRECT_VALUE = 2_679_000_000
FALSE_VALUE = 3_200_000_000


async def evaluate_case(adversarial):
    base = build_observations("arm_ipo_2023_revenue")[:3]
    observations = base + adversarial["observations"]

    ids = {
        **source_ids("arm_ipo_2023_revenue"),
        **adversarial["source_ids"],
    }

    documents = dict(load_documents("arm_ipo_2023"))
    documents.update({
        item["source"]: item["text"]
        for item in adversarial["documents"]
    })

    retrieved = [
        {
            "source": ids[observation.source],
            "score": 0.0,
            "text": documents[ids[observation.source]],
        }
        for observation in observations
    ]

    mapped = map_observations(
        retrieved,
        observations,
        ids,
    )

    started = perf_counter()

    evaluation = await evaluate_context(
        mapped,
        estimator=estimator_config(),
    )

    selected = select_context(
        mapped,
        evaluation,
        top_n=4,
    )

    latency_seconds = perf_counter() - started

    return evaluation, selected, latency_seconds


def build_judge_inputs(adversarial):
    base_observations = build_observations(
        "arm_ipo_2023_revenue"
    )[:3]
    observations = base_observations + adversarial["observations"]

    ids = {
        **source_ids("arm_ipo_2023_revenue"),
        **adversarial["source_ids"],
    }

    documents = dict(load_documents("arm_ipo_2023"))
    documents.update({
        item["source"]: item["text"]
        for item in adversarial["documents"]
    })

    results = []

    for observation in observations:
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
                "observed_at":
                    observation.observed_at.isoformat(),
                "source_modified_at":
                    observation.source_modified_at.isoformat(),
                "upstream_sources": upstream_ids,
                "cited_sources": cited_ids,
                "parent_assertion_ids":
                    list(observation.parent_assertion_ids),
            },
        })

    return results



DEPENDENT_RELATIONSHIPS = {
    ("false_copy_a", "false_origin"),
    ("false_copy_b", "false_origin"),
}

INDEPENDENT_RELATIONSHIPS = set()


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


async def run_trial(trial_number):
    dependent_case = source_dependence()
    independent_case = independent_sources_control()

    (
        dependent_eval,
        dependent_selected,
        dependent_braid_latency,
    ) = await evaluate_case(dependent_case)

    (
        independent_eval,
        independent_selected,
        independent_braid_latency,
    ) = await evaluate_case(independent_case)

    dependent_llm_judges = await evaluate_llm_judges(
        query="What was Arm Holdings' total revenue for fiscal 2023?",
        results=build_judge_inputs(dependent_case),
        expected_relationships=DEPENDENT_RELATIONSHIPS,
        include_text=False,
    )
    independent_llm_judges = await evaluate_llm_judges(
        query="What was Arm Holdings' total revenue for fiscal 2023?",
        results=build_judge_inputs(independent_case),
        expected_relationships=INDEPENDENT_RELATIONSHIPS,
        include_text=False,
    )

    dependent = {
        claim.claim.value: claim
        for claim in dependent_eval.claim_support
    }
    independent = {
        claim.claim.value: claim
        for claim in independent_eval.claim_support
    }

    return {
        "benchmark": "source_dependence",
        "trial": trial_number,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "correct_value": CORRECT_VALUE,
        "false_value": FALSE_VALUE,
        "dependent_treatment": {
            "braid_latency_seconds": dependent_braid_latency,
            "claims": [
                claim_record(claim)
                for claim in dependent_eval.claim_support
            ],
            "selected_context": selected_record(
                dependent_selected
            ),
            "llm_judges": dependent_llm_judges,
        },
        "independent_control": {
            "braid_latency_seconds": independent_braid_latency,
            "claims": [
                claim_record(claim)
                for claim in independent_eval.claim_support
            ],
            "selected_context": selected_record(
                independent_selected
            ),
            "llm_judges": independent_llm_judges,
        },
        "checks": {
            "dependent_correct_beats_false":
                dependent[CORRECT_VALUE].support
                > dependent[FALSE_VALUE].support,
            "false_independent_support_reduced":
                dependent[FALSE_VALUE]
                .estimated_independent_support_count
                < independent[FALSE_VALUE]
                .estimated_independent_support_count,
            "control_is_tied":
                abs(
                    independent[CORRECT_VALUE].support
                    - independent[FALSE_VALUE].support
                ) < 1e-9,
            "control_claims_tied_as_winners":
                independent[CORRECT_VALUE].is_attribute_max_support
                and independent[FALSE_VALUE].is_attribute_max_support,
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
        "benchmark": "source_dependence",
        "trial_count": len(trials),
        "generated_at_utc":
            datetime.now(timezone.utc).isoformat(),
        "dependent_treatment":
            summarize_condition(
                trials,
                "dependent_treatment",
            ),
        "independent_control":
            summarize_condition(
                trials,
                "independent_control",
            ),
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
    parser.add_argument(
        "--trials",
        type=int,
        default=1,
    )
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
            print(
                f"Running trial "
                f"{trial_number}/{args.trials}..."
            )

            trial = await run_trial(trial_number)
            trials.append(trial)

            handle.write(
                json.dumps(trial) + "\n"
            )
            handle.flush()

    summary = build_summary(trials)

    summary_output.write_text(
        json.dumps(summary, indent=2) + "\n"
    )

    run_manifest = manifest(
        benchmark="source_dependence",
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
