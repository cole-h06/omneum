import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from .cases import (
    CORRECT_VALUE,
    FALSE_VALUE,
    balanced_control,
    conflict,
)
from ...braid_rag import evaluate_context
from ...config import estimator_config
from ...reproducibility import manifest, write_manifest


OUTPUT_DIR = Path(
    "benchmarks/financial_dependency_suite/results/adversarial/"
    "conflicting_information"
)


def mapped_case(case):
    documents = {
        item["source"]: item["text"]
        for item in case["documents"]
    }

    return [
        {
            "retrieved": {
                "source": case["source_ids"][observation.source],
                "score": 0.0,
                "text": documents.get(
                    case["source_ids"][observation.source],
                    "",
                ),
            },
            "observation": observation,
        }
        for observation in case["observations"]
    ]


async def evaluate(case):
    started = perf_counter()

    evaluation = await evaluate_context(
        mapped_case(case),
        estimator=estimator_config(),
    )

    return evaluation, perf_counter() - started


def source_record(item):
    return {
        "source": {
            "kind": item.source.kind,
            "identifier": item.source.identifier,
        },
        "reliability": item.reliability,
    }


def claim_record(item):
    return {
        "claim": {
            "entity_namespace": item.claim.entity_namespace,
            "entity": item.claim.entity,
            "attribute": item.claim.attribute,
            "value": item.claim.value,
        },
        "support": item.support,
        "agreement_weight": item.agreement_weight,
        "is_attribute_max_support":
            item.is_attribute_max_support,
        "supporting_source_count":
            item.supporting_source_count,
        "estimated_independent_support_count":
            item.estimated_independent_support_count,
        "dependency_signal_coverage":
            item.dependency_signal_coverage,
        "supporting_sources": [
            {
                "source": {
                    "kind": supporter.source.kind,
                    "identifier":
                        supporter.source.identifier,
                },
                "independence": supporter.independence,
                "contribution": supporter.contribution,
            }
            for supporter in item.supporting_sources
        ],
        "conflicting_claims": [
            {
                "claim": {
                    "entity_namespace":
                        conflict.claim.entity_namespace,
                    "entity": conflict.claim.entity,
                    "attribute": conflict.claim.attribute,
                    "value": conflict.claim.value,
                },
                "support": conflict.support,
            }
            for conflict in item.conflicting_claims
        ],
    }


def evaluation_record(evaluation):
    return evaluation.explanation

def target_claims(evaluation):
    return {
        item.claim.value: item
        for item in evaluation.claim_support
        if item.claim.value in {
            CORRECT_VALUE,
            FALSE_VALUE,
        }
    }


async def main():
    treatment_eval, treatment_latency = await evaluate(
        conflict()
    )
    control_eval, control_latency = await evaluate(
        balanced_control()
    )

    treatment_claims = target_claims(treatment_eval)
    control_claims = target_claims(control_eval)

    result = {
        "benchmark": "conflicting_information",
        "treatment": {
            "omneum": evaluation_record(treatment_eval),
            "cold_integration_latency_seconds": treatment_latency,
        },
        "balanced_control": {
            "omneum": evaluation_record(control_eval),
            "cold_integration_latency_seconds": control_latency,
        },
        "checks": {
            "treatment_correct_wins": (
                treatment_claims[CORRECT_VALUE].support
                > treatment_claims[FALSE_VALUE].support
            ),
            "control_ties": abs(
                control_claims[CORRECT_VALUE].support
                - control_claims[FALSE_VALUE].support
            ) < 1e-9,
        },
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = OUTPUT_DIR / f"{run_id}.structural.json"
    manifest_output = OUTPUT_DIR / f"{run_id}.manifest.json"

    output_path.write_text(
        json.dumps(result, indent=2) + "\n"
    )

    run_manifest = manifest(
        benchmark="conflicting_information",
        track="structural",
        trials=1,
        inputs=[
            Path(__file__),
            Path(__file__).with_name("cases.py"),
        ],
        identifier=run_id,
    )
    write_manifest(manifest_output, run_manifest)

    print(json.dumps(result, indent=2))
    print(f"\nResult: {output_path}")
    print(f"Manifest: {manifest_output}")


if __name__ == "__main__":
    asyncio.run(main())
