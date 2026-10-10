import json
from time import perf_counter

from .clients import DEFAULT_MODELS, generate
from .generation import answer_from_context
from .naive_rag import rank_documents
from .semantic_reranker import rerank_bge, rerank_cohere

LLM_SELECTORS = tuple(
    (provider, DEFAULT_MODELS[provider])
    for provider in ("anthropic", "openai", "google")
)

# Transport constraint only: candidate membership, cardinality and uniqueness
# remain validated locally, identically for every frontier selector.
SELECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "selected_sources": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["selected_sources"],
    "additionalProperties": False,
}


def provider_error_diagnostics(exc):
    """Never serialize exception bodies, requests, headers, or credentials."""
    result = {"error_type": type(exc).__name__}
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(exc, "code", None)
    if isinstance(status, int):
        result["http_status"] = status
        if status == 429:
            result["error_category"] = "rate_or_quota_limit"
        elif status == 503:
            result["error_category"] = "service_unavailable"
    return result


def warm_local_models(query, candidates):
    documents = [
        (candidate["source"], candidate["text"])
        for candidate in candidates
    ]

    rank_documents(
        query,
        documents,
        top_k=1,
    )

    rerank_bge(
        query,
        candidates,
        top_n=1,
    )


def select_vector(query, candidates, *, top_n):
    documents = [
        (candidate["source"], candidate["text"])
        for candidate in candidates
    ]

    started = perf_counter()
    ranked = rank_documents(
        query,
        documents,
        top_k=top_n,
    )

    return {
        "selected": ranked,
        "latency_seconds": perf_counter() - started,
        "model": "all-MiniLM-L6-v2",
    }


def select_bge(query, candidates, *, top_n):
    started = perf_counter()
    selected = rerank_bge(
        query,
        candidates,
        top_n=top_n,
    )

    return {
        "selected": selected,
        "latency_seconds": perf_counter() - started,
        "model": "BAAI/bge-reranker-v2-m3",
    }


def select_cohere(query, candidates, *, top_n):
    return rerank_cohere(
        query,
        candidates,
        top_n=top_n,
    )


def select_cohere_safe(query, candidates, *, top_n):
    try:
        selection = select_cohere(
            query,
            candidates,
            top_n=top_n,
        )
    except Exception as exc:
        return {
            "selection": None,
            "failure": {
                "selected": [],
                "selection": {
                    "model": "rerank-v4.0-pro",
                    "provider": "cohere",
                    "latency_seconds": None,
                    "input_tokens": None,
                    "output_tokens": None,
                },
                "answer": None,
                "answer_score": "selection_failure",
                "generation": None,
                "failure_type": "provider_error",
                "response_diagnostics": provider_error_diagnostics(exc),
                "error": f"{type(exc).__name__}: {exc}",
            },
        }

    return {
        "selection": selection,
        "failure": None,
    }


def _extract_json(text):
    stripped = text.strip()

    if stripped.startswith("```"):
        lines = stripped.splitlines()[1:]

        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

        stripped = "\n".join(lines).strip()

    return json.loads(stripped)


async def select_llm(
    query,
    candidates,
    *,
    provider,
    model,
    top_n,
    thinking_level=None,
):
    source_ids = [
        candidate["source"]
        for candidate in candidates
    ]

    context = "\n\n".join(
        f"Source ID: {candidate['source']}\n"
        f"{candidate['text']}"
        for candidate in candidates
    )

    prompt = f"""Select the {top_n} sources that would provide the best context
for answering the question below.

Question:
{query}

Candidate sources:
{context}

Return only valid JSON in this exact form:
{{"selected_sources": ["source_id", "source_id"]}}

Use only source IDs from the candidate set.
Do not answer the question itself.
"""

    result = await generate(
        prompt,
        provider=provider,
        model=model,
        response_schema=SELECTION_SCHEMA,
        **({"thinking_level": thinking_level} if thinking_level is not None else {}),
    )

    try:
        parsed = _extract_json(result["text"])
        selected_ids = parsed["selected_sources"]

        if (
            not isinstance(selected_ids, list)
            or len(selected_ids) != top_n
            or len(set(selected_ids)) != len(selected_ids)
            or any(
                source_id not in source_ids
                for source_id in selected_ids
            )
        ):
            raise ValueError("invalid selected_sources")

        candidates_by_source = {
            candidate["source"]: candidate
            for candidate in candidates
        }

        selected = [
            candidates_by_source[source_id]
            for source_id in selected_ids
        ]
        parse_error = None

    except (
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        selected = []
        parse_error = str(exc)

    return {
        "selected": selected,
        "provider": result["provider"],
        "model": result["model"],
        "latency_seconds": result["latency_seconds"],
        "input_tokens": result["input_tokens"],
        "output_tokens": result["output_tokens"],
        "parse_error": parse_error,
        "raw_output": result["text"],
        "response_diagnostics": result.get("response_diagnostics", {}),
        **({"request_parameters": result["request_parameters"]} if "request_parameters" in result else {}),
    }


def provenance_context(candidates, observations, source_ids):
    by_source = {
        source_id: []
        for source_id in (
            candidate["source"]
            for candidate in candidates
        )
    }

    for observation in observations:
        source_id = source_ids.get(observation.source)

        if source_id not in by_source:
            continue

        by_source[source_id].append({
            "assertion_id": observation.observation_id,
            "observed_at": observation.observed_at.isoformat(),
            "source_modified_at": (
                observation.source_modified_at.isoformat()
                if observation.source_modified_at is not None
                else None
            ),
            "upstream_sources": [
                {
                    "kind": source.kind,
                    "identifier": source.identifier,
                }
                for source in observation.upstream_sources
            ],
            "cited_sources": [
                {
                    "kind": source.kind,
                    "identifier": source.identifier,
                }
                for source in observation.cited_sources
            ],
            "parent_assertion_ids": list(
                observation.parent_observation_ids
            ),
        })

    return by_source


async def select_llm_provenance(
    query,
    candidates,
    observations,
    source_ids,
    *,
    provider,
    model,
    top_n,
):
    candidate_ids = [
        candidate["source"]
        for candidate in candidates
    ]
    provenance = provenance_context(
        candidates,
        observations,
        source_ids,
    )

    context = "\n\n".join(
        f"Source ID: {candidate['source']}\n"
        f"Text: {candidate['text']}\n"
        f"Structured provenance: "
        f"{json.dumps(provenance[candidate['source']], sort_keys=True)}"
        for candidate in candidates
    )

    prompt = f"""Select the {top_n} sources that would provide the best context
for answering the question below.

Question:
{query}

Candidate sources:
{context}

Use both the source text and structured provenance when evaluating
the candidate context.

Return only valid JSON in this exact form:
{{"selected_sources": ["source_id", "source_id"]}}

Use only source IDs from the candidate set.
Do not answer the question itself.
"""

    result = await generate(
        prompt,
        provider=provider,
        model=model,
        response_schema=SELECTION_SCHEMA,
    )

    try:
        parsed = _extract_json(result["text"])
        selected_ids = parsed["selected_sources"]

        if (
            not isinstance(selected_ids, list)
            or len(selected_ids) != top_n
            or len(set(selected_ids)) != len(selected_ids)
            or any(
                source_id not in candidate_ids
                for source_id in selected_ids
            )
        ):
            raise ValueError("invalid selected_sources")

        candidates_by_source = {
            candidate["source"]: candidate
            for candidate in candidates
        }
        selected = [
            candidates_by_source[source_id]
            for source_id in selected_ids
        ]
        parse_error = None

    except (
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        selected = []
        parse_error = str(exc)

    return {
        "selected": selected,
        "provider": result["provider"],
        "model": result["model"],
        "latency_seconds": result["latency_seconds"],
        "input_tokens": result["input_tokens"],
        "output_tokens": result["output_tokens"],
        "parse_error": parse_error,
        "raw_output": result["text"],
        "response_diagnostics": result.get("response_diagnostics", {}),
    }


async def select_llm_provenance_safe(
    query,
    candidates,
    observations,
    source_ids,
    *,
    provider,
    model,
    top_n,
):
    try:
        return await select_llm_provenance(
            query,
            candidates,
            observations,
            source_ids,
            provider=provider,
            model=model,
            top_n=top_n,
        )
    except Exception as exc:
        return {
            "selected": [],
            "provider": provider,
            "model": model,
            "latency_seconds": None,
            "input_tokens": None,
            "output_tokens": None,
            "parse_error": None,
            "raw_output": None,
            "selection_failure": str(exc),
            "failure_type": "provider_error",
            "response_diagnostics": provider_error_diagnostics(exc),
        }


async def select_llm_safe(
    query,
    candidates,
    *,
    provider,
    model,
    top_n,
    thinking_level=None,
):
    try:
        selection = await select_llm(
            query,
            candidates,
            provider=provider,
            model=model,
            top_n=top_n,
            **({"thinking_level": thinking_level} if thinking_level is not None else {}),
        )
    except Exception as exc:
        return {
            "selection": None,
            "failure": {
                "selected": [],
                "selection": {
                    "model": model,
                    "provider": provider,
                    "latency_seconds": None,
                    "input_tokens": None,
                    "output_tokens": None,
                },
                "answer": None,
                "answer_score": "selection_failure",
                "generation": None,
                "failure_type": "provider_error",
                "response_diagnostics": provider_error_diagnostics(exc),
                "error": f"{type(exc).__name__}: {exc}",
            },
        }

    if selection["parse_error"] is not None:
        return {
            "selection": None,
            "failure": {
                "selected": [],
                "selection": {
                    "model": selection.get("model"),
                    "provider": selection.get("provider"),
                    "latency_seconds": selection["latency_seconds"],
                    "input_tokens": selection.get("input_tokens"),
                    "output_tokens": selection.get("output_tokens"),
                    "raw_output": selection.get("raw_output"),
                    "response_diagnostics": selection.get("response_diagnostics", {}),
                    **({"request_parameters": selection["request_parameters"]} if "request_parameters" in selection else {}),
                },
                "answer": None,
                "answer_score": "selection_failure",
                "generation": None,
                "failure_type": "parse_error",
                "error": selection["parse_error"],
            },
        }

    return {
        "selection": selection,
        "failure": None,
    }


def omneum_documents(selected):
    return [
        {
            "source": item["retrieved"]["source"],
            "text": item["retrieved"]["text"],
        }
        for item in selected
    ]


async def generate_answer(
    query,
    selected,
    *,
    provider,
    model,
):
    documents = [
        {
            "source": item["source"],
            "text": item["text"],
        }
        for item in selected
    ]

    return await answer_from_context(
        query,
        documents,
        provider=provider,
        model=model,
    )


async def generate_answer_safe(
    query,
    selected,
    *,
    provider,
    model,
):
    try:
        generation = await generate_answer(
            query,
            selected,
            provider=provider,
            model=model,
        )
    except Exception as exc:
        return {
            "generation": None,
            "failure": {
                "answer": None,
                "answer_score": "generation_failure",
                "response_diagnostics": provider_error_diagnostics(exc),
                "generation": None,
                "failure_type": "provider_error",
                "error": str(exc),
                "provider": provider,
                "model": model,
            },
        }

    diagnostics = generation.get("response_diagnostics") or {}
    refused = (
        diagnostics.get("stop_reason") == "refusal"
        or "refusal" in diagnostics.get("content_block_types", [])
        or "refusal" in diagnostics.get("finish_reasons", [])
    )
    failure_type = (
        "refusal" if refused
        else "empty_output" if not generation["text"].strip()
        else None
    )
    if failure_type is not None:
        return {
            "generation": generation,
            "failure": {
                "answer": generation["text"],
                "answer_score": "generation_failure",
                "generation": generation,
                "response_diagnostics": diagnostics,
                "failure_type": failure_type,
                "error": ("Generator explicitly refused." if refused
                          else "Generator returned no non-whitespace answer."),
                "provider": generation.get("provider", provider),
                "model": generation.get("model", model),
            },
        }
    return {"generation": generation, "failure": None}


async def select_omneum_reranked(
    query,
    candidates,
    observations,
    source_ids,
    *,
    estimator,
    top_n,
    evaluation_observations=None,
):
    from .omneum_rag import (
        evaluate_context,
        map_observations,
        select_context,
    )

    mapped = map_observations(
        candidates,
        observations,
        source_ids,
    )

    evaluation_mapped = mapped

    if evaluation_observations is not None:
        evaluation_mapped = [
            {"observation": observation}
            for observation in evaluation_observations
        ]

    started = perf_counter()

    evaluation = await evaluate_context(
        evaluation_mapped,
        estimator=estimator,
    )

    selected = select_context(
        query,
        mapped,
        evaluation,
        top_n=top_n,
    )

    latency = perf_counter() - started
    evaluation_latency_ms = getattr(
        evaluation,
        "evaluation_latency_ms",
        None,
    )

    return {
        "selected": omneum_documents(selected),
        "evaluation": evaluation,
        "latency_seconds": latency,
        "cold_integration_latency_seconds": latency,
        "evaluation_latency_seconds": (
            evaluation_latency_ms / 1000
            if evaluation_latency_ms is not None
            else None
        ),
        "model": "Omneum",
    }


async def select_omneum(
    candidates,
    observations,
    source_ids,
    *,
    estimator,
    top_n,
):
    """Apply reliability filtering only to the relevance-selected candidates."""
    from .omneum_rag import (
        evaluate_context,
        map_observations,
        select_reliable_context,
    )

    started = perf_counter()

    eligible_sources = {item["source"] for item in candidates}
    observations_by_id = {
        observation.observation_id: observation
        for observation in observations
    }
    source_by_key = {
        (observation.source.kind, observation.source.identifier): observation.source
        for observation in observations
    }

    evaluation_sources = set(eligible_sources)
    evaluation_observation_ids = {
        observation.observation_id
        for observation in observations
        if source_ids[observation.source] in eligible_sources
    }

    changed = True
    while changed:
        changed = False

        for observation in observations:
            if observation.observation_id not in evaluation_observation_ids:
                continue

            for ref in (
                *(observation.upstream_sources or ()),
                *(observation.cited_sources or ()),
            ):
                source = source_by_key.get((ref.kind, ref.identifier))
                if source is None:
                    continue
                source_id = source_ids[source]
                if source_id not in evaluation_sources:
                    evaluation_sources.add(source_id)
                    changed = True
                for related in observations:
                    if related.source == source and related.observation_id not in evaluation_observation_ids:
                        evaluation_observation_ids.add(related.observation_id)
                        changed = True

            for parent_id in observation.parent_observation_ids or ():
                parent = observations_by_id.get(parent_id)
                if parent is None:
                    continue
                if parent_id not in evaluation_observation_ids:
                    evaluation_observation_ids.add(parent_id)
                    changed = True
                source_id = source_ids[parent.source]
                if source_id not in evaluation_sources:
                    evaluation_sources.add(source_id)
                    changed = True

    evaluation_candidates = list(candidates)
    candidate_sources = {item["source"] for item in candidates}

    evaluation_candidates.extend(
        {
            "source": source_ids[observation.source],
            "text": "",
        }
        for observation in observations
        if (
            observation.observation_id in evaluation_observation_ids
            and source_ids[observation.source] not in candidate_sources
        )
    )

    mapped = map_observations(
        evaluation_candidates,
        observations,
        source_ids,
    )
    evaluation = await evaluate_context(mapped, estimator=estimator)

    eligible_mapped = [
        item
        for item in mapped
        if item["retrieved"]["source"] in eligible_sources
    ]
    selected = select_reliable_context(
        eligible_mapped,
        evaluation,
        top_n=top_n,
    )
    documents = omneum_documents(selected)
    latency = perf_counter() - started
    evaluation_latency_ms = getattr(evaluation, "evaluation_latency_ms", None)

    return {
        "selected": documents,
        "evaluation": evaluation,
        "latency_seconds": latency,
        "cold_integration_latency_seconds": latency,
        "evaluation_latency_seconds": (
            evaluation_latency_ms / 1000
            if evaluation_latency_ms is not None
            else None
        ),
        "model": "Omneum",
    }


def selection_record(selection):
    record = {
        "model": selection.get("model"),
        "provider": selection.get("provider"),
        "latency_seconds": selection["latency_seconds"],
    }

    if "cold_integration_latency_seconds" in selection:
        record["cold_integration_latency_seconds"] = (
            selection["cold_integration_latency_seconds"]
        )

    if "evaluation_latency_seconds" in selection:
        record["evaluation_latency_seconds"] = (
            selection["evaluation_latency_seconds"]
        )

    if "input_tokens" in selection:
        record["input_tokens"] = selection["input_tokens"]

    if "output_tokens" in selection:
        record["output_tokens"] = selection["output_tokens"]

    if "raw_output" in selection:
        record["raw_output"] = selection["raw_output"]

    return record


def application_record(selection, generation, answer_score):
    selection_data = selection_record(selection)

    generation_data = {
        "provider": generation["provider"],
        "model": generation["model"],
        "latency_seconds": generation["latency_seconds"],
        "input_tokens": generation["input_tokens"],
        "output_tokens": generation["output_tokens"],
    }

    return {
        "selected": [
            item["source"]
            for item in selection["selected"]
        ],
        "answer": generation["text"],
        "answer_score": answer_score,
        "selection": selection_data,
        "generation": generation_data,
        "end_to_end_latency_seconds": (
            selection["latency_seconds"]
            + generation["latency_seconds"]
        ),
    }
