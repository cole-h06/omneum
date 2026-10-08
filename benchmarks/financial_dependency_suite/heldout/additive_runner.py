"""Opt-in paired methods; frozen runner and scoring stay unchanged."""

import hashlib
import json

from benchmarks.financial_dependency_suite.application_comparison import (
    SELECTION_SCHEMA, generate_answer_safe, select_cohere_safe,
    select_llm_safe, select_omneum,
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


def _claude_selection_hash(query, candidates, *, model, depth):
    context = "\n\n".join(
        f"Source ID: {candidate['source']}\n{candidate['text']}"
        for candidate in candidates
    )
    prompt = f"""Select the {depth} sources that would provide the best context
for answering the question below.

Question:
{query}

Candidate sources:
{context}

Return only valid JSON in this exact form:
{{\"selected_sources\": [\"source_id\", \"source_id\"]}}

Use only source IDs from the candidate set.
Do not answer the question itself.
"""
    return _hash_request(provider="anthropic", model=model, prompt=prompt,
                         max_tokens=1024, response_schema=SELECTION_SCHEMA)


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


async def run_selection(method, case, *, provider=None, model=None, cohere_cache=None):
    candidates = application_candidates(case)
    top_n = case.context_budget

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
        depth = min(len(candidates), 2 * top_n)
        request_hash = _claude_selection_hash(
            case.question, candidates, model=model or "claude-sonnet-5-5", depth=depth,
        )
        response = await select_llm_safe(
            case.question, candidates, provider=provider or "anthropic",
            model=model or "claude-sonnet-5-5", top_n=depth,
        )
        if response["failure"] is not None:
            failure = response["failure"]
            selection = dict(failure.get("selection") or {})
            selection.update({
                "evaluator_provider": selection.get("provider", provider or "anthropic"),
                "evaluator_model": selection.get("model", model or "claude-sonnet-5-5"),
                "evaluator_input_tokens": selection.get("input_tokens"),
                "evaluator_output_tokens": selection.get("output_tokens"),
                "evaluator_raw_output": selection.get("raw_output"),
                "evaluator_response_diagnostics": selection.get("response_diagnostics", {}),
                "evaluator_latency_seconds": selection.get("latency_seconds"),
                "request_hash": request_hash,
                "request_hash_algorithm": "sha256 canonical provider/model/prompt/max_tokens/response_schema",
                "relevance_depth": depth,
                "relevance_model": model or "claude-sonnet-5-5",
                "timing_provenance": {
                    "evaluator": "Anthropic SDK request duration including client setup and response parsing",
                    "omneum": "not reached",
                },
            })
            failure["selection"] = selection
            failure["inference_cost"] = {"usd": None, "availability": "no_pricing_defined"}
            return {"failure": failure}

        relevance = response["selection"]
        if relevance.get("parse_error") or relevance.get("selection_failure"):
            relevance.update({
                "evaluator_provider": relevance.get("provider", provider or "anthropic"),
                "evaluator_model": relevance.get("model", model or "claude-sonnet-5-5"),
                "evaluator_input_tokens": relevance.get("input_tokens"),
                "evaluator_output_tokens": relevance.get("output_tokens"),
                "evaluator_raw_output": relevance.get("raw_output"),
                "evaluator_response_diagnostics": relevance.get("response_diagnostics", {}),
                "evaluator_latency_seconds": relevance.get("latency_seconds"),
                "request_hash": request_hash,
                "request_hash_algorithm": "sha256 canonical provider/model/prompt/max_tokens/response_schema",
                "relevance_depth": depth,
                "relevance_model": model or "claude-sonnet-5-5",
                "timing_provenance": {
                    "evaluator": "Anthropic SDK request duration including client setup and response parsing",
                    "omneum": "not reached",
                },
            })
            return {"failure": None, "selection": relevance}

        observations, source_ids = build_observations(case)
        reliability = await select_omneum(
            relevance["selected"], observations, source_ids,
            estimator=estimator_config(), top_n=top_n,
        )
        final_ids = [item["source"] for item in reliability["selected"]]
        shortlist_ids = {item["source"] for item in relevance["selected"]}
        if len(final_ids) != top_n or len(set(final_ids)) != top_n or not set(final_ids).issubset(shortlist_ids):
            return {"failure": None, "selection": {
                **reliability,
                "selected": [],
                "selection_failure": "Omneum did not return exactly the requested unique shortlist subset",
                "failure_type": "omneum_selection_contract",
                "relevance_depth": depth,
                "relevance_model": relevance["model"],
                "relevance_selected": relevance["selected"],
                "relevance_selected_sources": [item["source"] for item in relevance["selected"]],
                "evaluator_provider": relevance["provider"],
                "evaluator_model": relevance["model"],
                "evaluator_latency_seconds": relevance["latency_seconds"],
                "evaluator_input_tokens": relevance["input_tokens"],
                "evaluator_output_tokens": relevance["output_tokens"],
                "evaluator_raw_output": relevance["raw_output"],
                "evaluator_response_diagnostics": relevance.get("response_diagnostics", {}),
                "request_hash": request_hash,
                "request_hash_algorithm": "sha256 canonical provider/model/prompt/max_tokens/response_schema",
                "omneum_latency_seconds": reliability["latency_seconds"],
                "latency_seconds": relevance["latency_seconds"] + reliability["latency_seconds"],
                "timing_provenance": {
                    "evaluator": "Anthropic SDK request duration including client setup and response parsing",
                    "omneum": "full Omneum integration duration, including deployment and stdio client lifecycle",
                    "evaluation": "SDK evaluation_latency_seconds; includes SDK evaluation call work and local validation",
                },
            }}
        return {"failure": None, "selection": {
            **reliability,
            "selected": reliability["selected"],
            "relevance_depth": depth,
            "relevance_model": relevance["model"],
            "relevance_selected": relevance["selected"],
            "relevance_selected_sources": [item["source"] for item in relevance["selected"]],
            "evaluator_provider": relevance["provider"],
            "evaluator_model": relevance["model"],
            "evaluator_latency_seconds": relevance["latency_seconds"],
            "evaluator_input_tokens": relevance["input_tokens"],
            "evaluator_output_tokens": relevance["output_tokens"],
            "evaluator_raw_output": relevance["raw_output"],
            "evaluator_response_diagnostics": relevance.get("response_diagnostics", {}),
            "request_hash": request_hash,
            "request_hash_algorithm": "sha256 canonical provider/model/prompt/max_tokens/response_schema",
            "omneum_latency_seconds": reliability["latency_seconds"],
            "latency_seconds": relevance["latency_seconds"] + reliability["latency_seconds"],
            "timing_provenance": {
                "evaluator": "Anthropic SDK request duration, including client setup and response parsing",
                "omneum": "full Omneum integration duration, including deployment and stdio client lifecycle",
                "evaluation": "SDK evaluation_latency_seconds; includes SDK evaluation call work and local validation",
            },
        }}

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
    generator_provider,
    generator_model,
):
    if method not in {"cohere_omneum", "anthropic_omneum"} and not (method == "cohere" and cohere_cache is not None):
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
    )

    # These safe selectors return an envelope; the other selectors return
    # a bare selection (including provenance's inline failure metadata).
    if method in ("cohere", "cohere_omneum", "anthropic_omneum", "llm"):
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
        if method == "anthropic_omneum":
            failure["generation_request_hash"] = _generation_hash(
                case.question, selection["selected"], provider=generator_provider,
                model=generator_model,
            )
            failure["selection_score"] = score_selection(
                [item["source"] for item in selection["selected"]], truth,
            )
            failure["inference_cost"] = {"usd": None, "availability": "no_pricing_defined"}
        return failure

    generation = generation_result["generation"]
    if method == "anthropic_omneum":
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
