import asyncio
from pathlib import Path
from time import perf_counter

from .config import estimator_config

from omneum import (
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
    build_observations,
    source_ids,
)
from benchmarks.financial_dependency_suite.scoring import (
    load_ground_truth,
    score_relationships,
)
from examples.enterprise.config import example_deployment


CASES = (
    {
        "id": "arm_ipo_2023_revenue",
        "directory": "arm_ipo_2023",
        "question": "What was Arm Holdings' total revenue for fiscal 2023?",
    },
    {
        "id": "svb_collapse_2023_loss",
        "directory": "svb_collapse_2023",
        "question": (
            "What loss did SVB expect from the sale of its "
            "available-for-sale securities portfolio in March 2023?"
        ),
    },
    {
        "id": "smci_auditor_resignation_2024",
        "directory": "smci_auditor_resignation_2024",
        "question": (
            "Why did Ernst & Young resign as Super Micro Computer's "
            "auditor in October 2024?"
        ),
    },
)

CASES_ROOT = (
    Path(__file__).parent
    / "cases"
)


def ground_truth_path(case):
    return CASES_ROOT / case["directory"] / "ground_truth.json"


def source_id(reference, case):
    for source, benchmark_id in source_ids(case["id"]).items():
        if (
            source.kind == reference.kind
            and source.identifier == reference.identifier
        ):
            return benchmark_id

    raise KeyError(reference.identifier)


def score_omneum(result, case):
    threshold = result.dependency_cluster_threshold

    predicted = {
        frozenset(
            (
                source_id(pair.source_a, case),
                source_id(pair.source_b, case),
            )
        )
        for pair in result.pairwise_dependencies
        if pair.dependency >= threshold
    }

    truth = load_ground_truth(ground_truth_path(case))
    return score_relationships(predicted, truth)


def score_llm_judge(result, case):
    predicted = {
        frozenset(
            (
                relationship["source"],
                relationship["depends_on"],
            )
        )
        for relationship in result["relationships"]
    }

    truth = load_ground_truth(ground_truth_path(case))
    return score_relationships(predicted, truth)




async def run_omneum(case):
    observations = build_observations(case["id"])

    with example_deployment() as (config, server):
        async with open_stdio_client(config, server) as client:
            start = perf_counter()

            result = await client.evaluate_assertion(
                observations,
                estimator=estimator_config(),
            )

            latency_ms = (perf_counter() - start) * 1000

    return {
        "result": result,
        "latency_ms": latency_ms,
    }


async def run_naive_rag(case):
    return await naive_rag_answer(
        case["question"],
        case_directory=case["directory"],
    )


async def run_llm_judge(case):
    return await judge_dependencies(
        case["question"],
        case_directory=case["directory"],
    )


def render_omneum(result, case):
    print("=== OMNEUM ===")
    print()

    for claim in result.claim_support:
        print(explain_claim(claim))
        print()

    print("Pair dependencies")
    for pair in result.pairwise_dependencies:
        if pair.dependency > 0.0:
            print(explain_dependency(pair))
            print()

    print("=== SCORE ===")
    print(score_omneum(result, case))
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


def render_llm_judge(result, case):
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
    print(score_llm_judge(result, case))
    print()
    print(f"Model: {generation['model']}")
    print(f"Input tokens: {generation['input_tokens']}")
    print(f"Output tokens: {generation['output_tokens']}")
    print(f"Latency: {generation['latency_seconds']:.2f}s")


async def run_case(case):
    print()
    print("=" * 72)
    print(f"CASE: {case['id']}")
    print("=" * 72)
    print()

    omneum_run = await run_omneum(case)
    render_omneum(omneum_run["result"], case)
    omneum_score = score_omneum(omneum_run["result"], case)

    print(f"Evaluation latency: {omneum_run['latency_ms']:.2f}ms")
    print("LLM tokens: 0")
    print("LLM cost: $0.0000")
    print()

    naive_result = await run_naive_rag(case)
    render_naive_rag(naive_result)
    print()

    judge_result = await run_llm_judge(case)
    render_llm_judge(judge_result, case)
    judge_score = score_llm_judge(judge_result, case)

    return {
        "omneum": {
            "score": omneum_score,
            "latency_ms": omneum_run["latency_ms"],
            "input_tokens": 0,
            "output_tokens": 0,
        },
        "naive": {
            "latency_seconds": naive_result["generation"]["latency_seconds"],
            "input_tokens": naive_result["generation"]["input_tokens"],
            "output_tokens": naive_result["generation"]["output_tokens"],
        },
        "judge": {
            "score": judge_score,
            "latency_seconds": judge_result["generation"]["latency_seconds"],
            "input_tokens": judge_result["generation"]["input_tokens"],
            "output_tokens": judge_result["generation"]["output_tokens"],
        },
    }


async def run_suite():
    results = []

    for case in CASES:
        results.append(await run_case(case))

    omneum_tp = sum(r["omneum"]["score"]["true_positive"] for r in results)
    omneum_fp = sum(r["omneum"]["score"]["false_positive"] for r in results)
    omneum_fn = sum(r["omneum"]["score"]["false_negative"] for r in results)

    judge_tp = sum(r["judge"]["score"]["true_positive"] for r in results)
    judge_fp = sum(r["judge"]["score"]["false_positive"] for r in results)
    judge_fn = sum(r["judge"]["score"]["false_negative"] for r in results)

    omneum_precision = (
        omneum_tp / (omneum_tp + omneum_fp)
        if omneum_tp + omneum_fp else 0.0
    )
    omneum_recall = (
        omneum_tp / (omneum_tp + omneum_fn)
        if omneum_tp + omneum_fn else 0.0
    )
    judge_precision = (
        judge_tp / (judge_tp + judge_fp)
        if judge_tp + judge_fp else 0.0
    )
    judge_recall = (
        judge_tp / (judge_tp + judge_fn)
        if judge_tp + judge_fn else 0.0
    )

    omneum_latency = sum(
        r["omneum"]["latency_ms"] for r in results
    ) / len(results)

    naive_latency = sum(
        r["naive"]["latency_seconds"] for r in results
    ) / len(results) * 1000

    judge_latency = sum(
        r["judge"]["latency_seconds"] for r in results
    ) / len(results) * 1000

    naive_tokens = sum(
        r["naive"]["input_tokens"] + r["naive"]["output_tokens"]
        for r in results
    )
    judge_tokens = sum(
        r["judge"]["input_tokens"] + r["judge"]["output_tokens"]
        for r in results
    )

    print()
    print("=" * 94)
    print("PERFORMANCE LEADERSHIP MATRIX")
    print("=" * 94)
    print()
    print(
        f"{'Method':<20} "
        f"{'Dependency precision':>20} "
        f"{'Dependency recall':>18} "
        f"{'Avg latency':>16} "
        f"{'LLM tokens':>12}"
    )
    print("-" * 94)
    print(
        f"{'Omneum':<20} "
        f"{omneum_precision:>20.2%} "
        f"{omneum_recall:>18.2%} "
        f"{omneum_latency:>13.2f} ms "
        f"{0:>12}"
    )
    print(
        f"{'Naive Vector RAG':<20} "
        f"{'N/A':>20} "
        f"{'N/A':>18} "
        f"{naive_latency:>13.2f} ms "
        f"{naive_tokens:>12}"
    )
    print(
        f"{'LLM-as-Judge':<20} "
        f"{judge_precision:>20.2%} "
        f"{judge_recall:>18.2%} "
        f"{judge_latency:>13.2f} ms "
        f"{judge_tokens:>12}"
    )
    print()
    print(
        "N/A: Naive Vector RAG does not estimate "
        "source-dependency relationships."
    )
    print()


def main():
    asyncio.run(run_suite())


if __name__ == "__main__":
    main()
