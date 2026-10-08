"""Opt-in paired methods; frozen runner and scoring stay unchanged."""

import hashlib
import json
from copy import deepcopy
from dataclasses import asdict

from benchmarks.financial_dependency_suite.application_comparison import (
    generate_answer_safe, select_cohere_safe, select_omneum,
)
from benchmarks.financial_dependency_suite.config import estimator_config

from . import runner as frozen
from .loader import application_candidates, build_observations
from .scoring import score_answer, score_selection


def _hash_request(*, provider, model, prompt, max_tokens, response_schema=None):
    payload = {"provider": provider, "model": model, "prompt": prompt,
               "max_tokens": max_tokens, "response_schema": response_schema}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _generation_hash(query, documents, *, provider, model):
    context = "\n\n".join(
        f"Source: {item['source']}\n{item['text']}" for item in documents
    )
    prompt = f"""Answer the question using only the sources below.

Question:

{query}

Sources:

{context}

Give a concise answer and identify which sources support it.
"""
    return _hash_request(provider=provider, model=model, prompt=prompt, max_tokens=1024)


async def run_selection(method, case, *, provider=None, model=None, cohere_cache=None, bge_relevance=None, cohere_relevance=None):
    candidates = application_candidates(case)
    top_n = case.context_budget

    if bge_relevance is not None and cohere_relevance is not None:
        raise ValueError("only one shared relevance stage may be supplied")
    if bge_relevance is not None or cohere_relevance is not None:
        stage = "bge" if bge_relevance is not None else "cohere"
        if cohere_relevance is not None and cohere_relevance["failure"] is not None:
            failure = deepcopy(cohere_relevance["failure"])
            failure["selection"]["cohere_relevance_result"] = deepcopy(cohere_relevance)
            failure["selection"]["context_budget"] = top_n
            return {"failure": failure, "selection": None}
        relevance = bge_relevance if stage == "bge" else cohere_relevance["selection"]
        shortlist = deepcopy(relevance["selected"])
        telemetry = {
            f"{stage}_relevance": deepcopy(relevance),
            "relevance_depth": len(shortlist),
            "relevance_model": relevance["model"],
            "relevance_selected_sources": [item["source"] for item in shortlist],
            f"{stage}_latency_seconds": relevance["latency_seconds"],
            f"{stage}_shortlist_hash": hashlib.sha256(json.dumps(
                shortlist, sort_keys=True, separators=(",", ":"),
            ).encode()).hexdigest(),
            "context_budget": top_n,
        }
        if stage == "cohere":
            telemetry["cohere_relevance_result"] = deepcopy(cohere_relevance)
            telemetry["cohere_billed_search_units"] = relevance.get("billed_search_units")
            telemetry["cohere_input_tokens"] = relevance.get("input_tokens")
            telemetry["cohere_output_tokens"] = relevance.get("output_tokens")
        if method == f"{stage}_anthropic" or (stage == "bge" and method == "bge_openai"):
            judged = await frozen.select_llm_safe(
                case.question, shortlist, provider=provider, model=model, top_n=top_n,
            )
            if judged["failure"] is not None:
                selected = judged["failure"]["selection"]
            else:
                selected = judged["selection"]
            selected.update({
                "evaluator_provider": provider,
                "evaluator_model": model,
                "evaluator_latency_seconds": selected.get("latency_seconds"),
                "evaluator_input_tokens": selected.get("input_tokens"),
                "evaluator_output_tokens": selected.get("output_tokens"),
            })
        elif method == f"{stage}_omneum":
            observations, source_ids = build_observations(case)
            selected = await select_omneum(
                shortlist, observations, source_ids, estimator=estimator_config(), top_n=top_n,
            )
            selected.update({
                "omneum_latency_seconds": selected["latency_seconds"],
                "evaluator_provider": "local", "evaluator_model": "Omneum",
                "evaluator_latency_seconds": selected.get("evaluation_latency_seconds"),
                "evaluator_input_tokens": 0, "evaluator_output_tokens": 0,
                "evaluator_response_diagnostics": {"model_api_calls": 0},
            })
            judged = {"failure": None, "selection": selected}
        else:
            raise ValueError(f"shared {stage} shortlist supplied to an unrelated method")
        judge_latency = selected.get("latency_seconds")
        selected.update(telemetry)
        selected["latency_seconds"] = (
            relevance["latency_seconds"] + judge_latency if judge_latency is not None else None
        )
        if judged["failure"] is None:
            ids = [item["source"] for item in selected["selected"]]
            if len(ids) != top_n or len(set(ids)) != top_n or not set(ids).issubset(
                item["source"] for item in shortlist
            ):
                selected.update({"selected": [], "selection_failure": "Invalid final shortlist subset",
                                 "failure_type": "paired_selection_contract"})
        return judged

    if method in {"bge_openai", "bge_anthropic", "cohere_anthropic"}:
        raise ValueError(f"{method} requires the paired shared shortlist")

    if method in ("cohere", "cohere_omneum") and cohere_cache is not None:
        depth = min(len(candidates), 2 * top_n)
        result = cohere_cache.select(
            case.question, candidates, depth=depth, selector=select_cohere_safe,
        )
        if result["failure"] is not None:
            return result
        relevance = result["selection"]
        telemetry = {
            "relevance_depth": depth,
            "relevance_model": relevance["model"],
            "relevance_selected_sources": [item["source"] for item in relevance["selected"]],
            "relevance_selected": relevance["selected"],
            "cohere_latency_seconds": relevance["latency_seconds"],
            **{key: relevance[key] for key in (
                "cohere_cache_hit", "cohere_request_hash", "cohere_response_latency_seconds",
            )},
        }
        if method == "cohere":
            return {"failure": None, "selection": {
                **relevance, **telemetry, "selected": relevance["selected"][:top_n],
            }}
        observations, source_ids = build_observations(case)
        reliability = await select_omneum(
            relevance["selected"], observations, source_ids,
            estimator=estimator_config(), top_n=top_n,
        )
        return {"failure": None, "selection": {
            **reliability, **telemetry,
            "omneum_latency_seconds": reliability["latency_seconds"],
            "latency_seconds": relevance["latency_seconds"] + reliability["latency_seconds"],
        }}

    if method == "anthropic_omneum":
        observations, source_ids = build_observations(case)
        estimator = estimator_config()
        request = {
            "candidates": candidates,
            "observations": [asdict(observation) for observation in observations],
            "estimator": asdict(estimator),
            "top_n": top_n,
        }
        request_hash = hashlib.sha256(json.dumps(
            request, sort_keys=True, separators=(",", ":"), default=str,
        ).encode("utf-8")).hexdigest()
        reliability = await select_omneum(
            candidates, observations, source_ids,
            estimator=estimator, top_n=top_n,
        )
        selection = {
            **reliability,
            "candidate_pool_size": len(candidates),
            "candidate_pool_sources": [item["source"] for item in candidates],
            "evaluator_provider": "local",
            "evaluator_model": "Omneum",
            "evaluator_latency_seconds": reliability.get("evaluation_latency_seconds"),
            "evaluator_input_tokens": 0,
            "evaluator_output_tokens": 0,
            "evaluator_raw_output": None,
            "evaluator_response_diagnostics": {"model_api_calls": 0},
            "request_hash": request_hash,
            "request_hash_algorithm": "sha256 canonical candidates/observations/estimator/top_n (default=str)",
            "omneum_latency_seconds": reliability["latency_seconds"],
            "timing_provenance": {
                "evaluator": "local Omneum SDK evaluation_latency_seconds; no model API inference",
                "omneum": "full Omneum integration duration, including deployment and stdio client lifecycle",
                "evaluation": "SDK evaluation_latency_seconds; includes SDK evaluation call work and local validation",
            },
        }
        final_ids = [item["source"] for item in reliability["selected"]]
        candidate_ids = {item["source"] for item in candidates}
        if len(final_ids) != top_n or len(set(final_ids)) != top_n or not set(final_ids).issubset(candidate_ids):
            selection.update({
                "selected": [],
                "selection_failure": "Omneum did not return exactly the requested unique candidate subset",
                "failure_type": "omneum_selection_contract",
            })
        return {"failure": None, "selection": selection}

    if method == "cohere_omneum":
        from .cohere_cache import CohereResponseCache
        return await run_selection(method, case, cohere_cache=CohereResponseCache())

    return await frozen.run_selection(method, case, provider=provider, model=model)


async def run_method(
    method,
    case,
    truth,
    *,
    provider=None,
    model=None,
    cohere_cache=None,
    bge_relevance=None,
    cohere_relevance=None,
    generator_provider,
    generator_model,
):
    paired = bge_relevance is not None or cohere_relevance is not None
    if not paired and method not in {"bge_openai", "bge_anthropic", "cohere_anthropic", "cohere_omneum", "anthropic_omneum"} and not (method == "cohere" and cohere_cache is not None):
        return await frozen.run_method(
            method, case, truth, provider=provider, model=model,
            generator_provider=generator_provider, generator_model=generator_model,
        )

    selection = await run_selection(
        method,
        case,
        provider=provider,
        model=model,
        cohere_cache=cohere_cache,
        bge_relevance=bge_relevance,
        cohere_relevance=cohere_relevance,
    )

    # These safe selectors return an envelope; the other selectors return
    # a bare selection (including provenance's inline failure metadata).
    if paired or method in ("cohere", "cohere_omneum", "anthropic_omneum", "llm"):
        if selection["failure"] is not None:
            return selection["failure"]
        selection = selection["selection"]

    if selection.get("selection_failure") is not None:
        result = {
            "selected": [],
            "answer": None,
            "answer_score": "selection_failure",
            "selection": selection,
            "generation": None,
            "failure_type": selection["failure_type"],
            "error": selection["selection_failure"],
        }
        if method == "anthropic_omneum":
            result["inference_cost"] = {"usd": None, "availability": "no_pricing_defined"}
        return result

    if selection.get("parse_error") is not None:
        result = {
            "selected": [],
            "answer": None,
            "answer_score": "selection_failure",
            "selection": selection,
            "generation": None,
            "failure_type": "parse_error",
            "error": selection["parse_error"],
        }
        if method == "anthropic_omneum":
            result["inference_cost"] = {"usd": None, "availability": "no_pricing_defined"}
        return result

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
        if paired or method == "anthropic_omneum":
            failure["generation_request_hash"] = _generation_hash(
                case.question, selection["selected"], provider=generator_provider,
                model=generator_model,
            )
            failure["selection_score"] = score_selection(
                [item["source"] for item in selection["selected"]], truth,
            )
            failure["inference_cost"] = {"usd": None, "availability": "no_pricing_defined"}
            if failure.get("generation") is not None:
                failure["end_to_end_latency_seconds"] = (
                    selection["latency_seconds"] + failure["generation"]["latency_seconds"]
                )
        return failure

    generation = generation_result["generation"]
    if paired or method == "anthropic_omneum":
        generation["request_hash"] = _generation_hash(
            case.question, selection["selected"], provider=generator_provider,
            model=generation["model"],
        )
        generation["timing_provenance"] = "Anthropic SDK request duration including client setup and response parsing"

    selected_sources = [
        item["source"]
        for item in selection["selected"]
    ]

    result = {
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
    if method == "anthropic_omneum":
        result["inference_cost"] = {"usd": None, "availability": "no_pricing_defined"}
    return result
