import asyncio

from omneum import (
    DependencyEstimatorConfig,
    explain_claim,
    explain_dependency,
    open_stdio_client,
)

from benchmarks.financial_dependency_suite.llm_judge import (
    judge_dependencies,
)
from benchmarks.financial_dependency_suite.naive_rag import (
    answer as naive_rag_answer,
)
from benchmarks.financial_dependency_suite.observations import (
    SOURCE_IDS,
    build_observations,
)
from benchmarks.financial_dependency_suite.scoring import (
    load_ground_truth,
    score_relationships,
)
from examples.enterprise.config import example_deployment


GROUND_TRUTH = (
    "benchmarks/financial_dependency_suite/"
    "cases/arm_ipo_2023/ground_truth.json"
)

QUESTION = "What was Arm Holdings' total revenue for fiscal 2023?"


def source_id(reference):
    for source, benchmark_id in SOURCE_IDS.items():
        if (
            source.kind == reference.kind
            and source.identifier == reference.identifier
        ):
            return benchmark_id

    raise KeyError(reference.identifier)


def score_omneum(result):
    threshold = result.dependency_cluster_threshold

    predicted = {
        frozenset(
            (
                source_id(pair.source_a),
                source_id(pair.source_b),
            )
        )
        for pair in result.pairwise_dependencies
        if pair.dependency >= threshold
    }

    truth = load_ground_truth(GROUND_TRUTH)
    return score_relationships(predicted, truth)


def score_llm_judge(result):
    predicted = {
        frozenset(
            (
                relationship["source"],
                relationship["depends_on"],
            )
        )
        for relationship in result["relationships"]
    }

    truth = load_ground_truth(GROUND_TRUTH)
    return score_relationships(predicted, truth)


def estimator_config():
    return DependencyEstimatorConfig(
        upstream_weight=25.0,
        citation_weight=20.0,
        assertion_lineage_weight=20.0,
        ownership_weight=10.0,
        temporal_weight=10.0,
        graph_weight=15.0,
        temporal_window_seconds=172_800.0,
        estimator_version="dependency-estimator-v1",
        dependency_cluster_threshold=0.4,
    )


async def run_omneum():
    observations = build_observations()

    with example_deployment() as (config, server):
        async with open_stdio_client(config, server) as client:
            return await client.evaluate_assertion(
                observations,
                estimator=estimator_config(),
            )


async def run_naive_rag():
    return await naive_rag_answer(QUESTION)


async def run_llm_judge():
    return await judge_dependencies(QUESTION)


def render_omneum(result):
    print("=== OMNEUM ===")
    print()

    print("Claims")
    for claim in result.claim_support:
        print(explain_claim(claim))
        print()

    print("Pair dependencies")
    for pair in result.pairwise_dependencies:
        if pair.dependency > 0.0:
            print(explain_dependency(pair))
            print()

    print("=== SCORE ===")
    print(score_omneum(result))
    print()


def render_naive_rag(result):
    generation = result["generation"]

    print("=== NAIVE VECTOR RAG ===")
    print()
    print(result["answer"])
    print()

    print(f"Model: {generation['model']}")
    print(f"Input tokens: {generation['input_tokens']}")
    print(f"Output tokens: {generation['output_tokens']}")
    print(f"Latency: {generation['latency_seconds']:.2f}s")


def render_llm_judge(result):
    generation = result["generation"]

    print("=== LLM-AS-JUDGE ===")
    print()

    for relationship in result["relationships"]:
        print(
            f"{relationship['source']} -> "
            f"{relationship['depends_on']} "
            f"({relationship['relationship_type']}, "
            f"{relationship['confidence']:.2f})"
        )

    print()
    print("=== SCORE ===")
    print(score_llm_judge(result))
    print()

    print(f"Model: {generation['model']}")
    print(f"Input tokens: {generation['input_tokens']}")
    print(f"Output tokens: {generation['output_tokens']}")
    print(f"Latency: {generation['latency_seconds']:.2f}s")


async def run_suite():
    omneum_result = await run_omneum()
    render_omneum(omneum_result)

    naive_result = await run_naive_rag()
    render_naive_rag(naive_result)
    print()

    judge_result = await run_llm_judge()
    render_llm_judge(judge_result)


def main():
    asyncio.run(run_suite())


if __name__ == "__main__":
    main()