from benchmarks.financial_dependency_suite.application_comparison import (
    generate_answer_safe,
    select_bge,
    select_omneum_reranked,
    select_omneum,
    select_cohere_safe,
    select_llm_provenance_safe,
    select_llm_safe,
    select_vector,
)
from benchmarks.financial_dependency_suite.config import estimator_config

from .loader import application_candidates, build_observations
from .scoring import score_answer, score_selection


async def run_selection(
    method,
    case,
    *,
    provider=None,
    model=None,
):
    candidates = application_candidates(case)
    top_n = case.context_budget

    if method == "vector":
        return select_vector(
            case.question,
            candidates,
            top_n=top_n,
        )

    if method == "bge":
        return select_bge(
            case.question,
            candidates,
            top_n=top_n,
        )

    if method == "cohere":
        result = select_cohere_safe(
            case.question,
            candidates,
            top_n=top_n,
        )
        return result

    if method == "llm":
        return await select_llm_safe(
            case.question,
            candidates,
            provider=provider,
            model=model,
            top_n=top_n,
        )

    observations, source_ids = build_observations(case)

    if method == "bge_omneum":
        relevance_depth = min(len(candidates), 2 * top_n)
        relevance = select_bge(case.question, candidates, top_n=relevance_depth)
        reliability = await select_omneum(
            relevance["selected"],
            observations,
            source_ids,
            estimator=estimator_config(),
            top_n=top_n,
        )
        return {
            **reliability,
            "relevance_depth": relevance_depth,
            "relevance_model": relevance["model"],
            "relevance_selected_sources": [
                item["source"] for item in relevance["selected"]
            ],
            "bge_latency_seconds": relevance["latency_seconds"],
            "omneum_latency_seconds": reliability["latency_seconds"],
            "latency_seconds": (
                relevance["latency_seconds"] + reliability["latency_seconds"]
            ),
        }

    if method == "llm_provenance":
        return await select_llm_provenance_safe(
            case.question,
            candidates,
            observations,
            source_ids,
            provider=provider,
            model=model,
            top_n=top_n,
        )

    if method == "omneum":
        return await select_omneum_reranked(
            case.question,
            candidates,
            observations,
            source_ids,
            estimator=estimator_config(),
            top_n=top_n,
        )

    raise ValueError(f"unknown method: {method}")


async def run_method(
    method,
    case,
    truth,
    *,
    provider=None,
    model=None,
    generator_provider,
    generator_model,
):
    selection = await run_selection(
        method,
        case,
        provider=provider,
        model=model,
    )

    # These safe selectors return an envelope; the other selectors return
    # a bare selection (including provenance's inline failure metadata).
    if method in ("cohere", "llm"):
        if selection["failure"] is not None:
            return selection["failure"]
        selection = selection["selection"]

    if selection.get("selection_failure") is not None:
        return {
            "selected": [],
            "answer": None,
            "answer_score": "selection_failure",
            "selection": selection,
            "generation": None,
            "failure_type": selection["failure_type"],
            "error": selection["selection_failure"],
        }

    if selection.get("parse_error") is not None:
        return {
            "selected": [],
            "answer": None,
            "answer_score": "selection_failure",
            "selection": selection,
            "generation": None,
            "failure_type": "parse_error",
            "error": selection["parse_error"],
        }

    generation_result = await generate_answer_safe(
        case.question,
        selection["selected"],
        provider=generator_provider,
        model=generator_model,
    )

    if generation_result["failure"] is not None:
        failure = generation_result["failure"]
        failure["selected"] = [
            item["source"]
            for item in selection["selected"]
        ]
        failure["selection"] = selection
        return failure

    generation = generation_result["generation"]

    selected_sources = [
        item["source"]
        for item in selection["selected"]
    ]

    return {
        "selected": selected_sources,
        "selection_score": score_selection(
            selected_sources,
            truth,
        ),
        "answer": generation["text"],
        "answer_score": score_answer(
            generation["text"],
            truth,
        ),
        "selection": selection,
        "generation": generation,
        "end_to_end_latency_seconds": (
            selection["latency_seconds"]
            + generation["latency_seconds"]
        ),
    }
