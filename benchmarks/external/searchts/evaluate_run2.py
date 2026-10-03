"""Evaluate saved SearchTS retrievals: python -m benchmarks.external.searchts.evaluate."""

import asyncio
from dataclasses import fields, is_dataclass
from datetime import datetime
import json
from pathlib import Path
from uuid import NAMESPACE_URL

from omneum import (
    Claim, Observation, Retrieval, Source, SourceReference,
    open_stdio_client,
)
from omneum.explanations import explain_evaluation
from omneum.sources import internal_source_id

from benchmarks.financial_dependency_suite.config import estimator_config
from benchmarks.financial_dependency_suite.deployment import benchmark_deployment


DATA = Path(__file__).resolve().parent / "data" / "run2"
CLAIM_TEXT = (
    "Go 1.22 changes for-loop variables so each iteration creates new variables, "
    "avoiding accidental sharing bugs."
)


def load_observations():
    observations = []
    for filename, backend in (
        ("cole-searchts-eval4-curl_cffi.json", "curl_cffi"),
        ("cole-searchts-eval4-stealth.json", "stealth-browser"),
    ):
        result = json.loads((DATA / filename).read_text(encoding="utf-8"))
        if result["backend"] != backend or result["status"] != 200:
            raise ValueError(f"Unexpected backend or unsuccessful retrieval: {filename}")
        if not result["text"].strip():
            raise ValueError(f"Empty retrieval text: {filename}")
        url = result["final_url"]
        observed_at = datetime.fromisoformat(result["fetched_at"].replace("Z", "+00:00"))
        assertion_id = f"searchts:{backend}:{url}"
        observations.append(Observation(
            assertion_id=assertion_id,
            source=Source(
                kind="internal_service",
                identifier=internal_source_id(str(NAMESPACE_URL), f"searchts:{backend}"),
            ),
            claim=Claim(
                "service", "go", "loop_variable_scope",
                CLAIM_TEXT,
            ),
            observed_at=observed_at,
            # The two retrievals point to different web documents.
            # Ownership, publication time and lineage remain unspecified.
            upstream_sources=(SourceReference("web_document", url),),
            retrievals=(Retrieval(
                retrieval_id=assertion_id,
                kind="searchts",
                resource_id=url,
                retrieved_at=observed_at,
                fields=result,
            ),),
            metadata={"backend": backend, "input_file": filename, "document_url": url},
        ))
    if observations[0].claim != observations[1].claim:
        raise ValueError("The captures must contain the same claim")
    return tuple(observations)


def json_value(value):
    """Serialize public dataclass fields, exposing Claim.value instead of bytes."""
    if isinstance(value, Claim):
        return {name: getattr(value, name) for name in (
            "entity_namespace", "entity", "attribute", "value",
        )}
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {item.name: json_value(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_value(item) for item in value]
    return value


async def main():
    observations = load_observations()
    estimator = estimator_config()
    with benchmark_deployment() as (config, server):
        async with open_stdio_client(config, server) as client:
            evaluation = await client.evaluate_context(observations, estimator=estimator)

    output = DATA / "run2_evaluation.json"
    output.write_text(json.dumps(json_value({
        "observations": observations,
        "estimator": estimator,
        "evaluation": evaluation,
    }), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    labels = {item.source: item.metadata["backend"] for item in observations}
    print(explain_evaluation(evaluation))
    print(f"\nSource count: {len(evaluation.source_reliability)}")
    print(f"Claim count: {len(evaluation.claim_support)}")
    print("\nSource reliability")
    for item in evaluation.source_reliability:
        print(f"  {labels[item.source]}: {item.reliability:.4f}")
    print(f"\nDependencies: {len(evaluation.pairwise_dependencies)} source pair(s)")
    dependency_labels = {
        SourceReference(source.kind, source.identifier): label
        for source, label in labels.items()
    }
    for item in evaluation.pairwise_dependencies:
        print(f"{dependency_labels[item.source_a]} ↔ {dependency_labels[item.source_b]}")
        print(f"Dependency: {item.dependency:.4f}")
    conflicts = sum(len(item.conflicting_claims) for item in evaluation.claim_support)
    print(f"\nConflicts: {conflicts}")
    print(f"Convergence iterations: {evaluation.convergence.iterations}")
    print("\nTwo retrieval backends; different web documents on different hosts.")
    print(f"Structured result: {output.relative_to(DATA.parents[3])}")


if __name__ == "__main__":
    asyncio.run(main())
