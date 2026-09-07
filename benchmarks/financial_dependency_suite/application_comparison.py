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
    }


async def select_llm_safe(
    query,
    candidates,
    *,
    provider,
    model,
    top_n,
):
    try:
        selection = await select_llm(
            query,
            candidates,
            provider=provider,
            model=model,
            top_n=top_n,
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


def braid_documents(selected):
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
                "generation": None,
                "failure_type": "provider_error",
                "error": str(exc),
                "provider": provider,
                "model": model,
            },
        }

    return {
        "generation": generation,
        "failure": None,
    }


async def select_braid(
    candidates,
    observations,
    source_ids,
    *,
    estimator,
    top_n,
    evaluation_observations=None,
):
    from .braid_rag import (
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
        "selected": braid_documents(selected),
        "evaluation": evaluation,
        "latency_seconds": latency,
        "cold_integration_latency_seconds": latency,
        "evaluation_latency_seconds": (
            evaluation_latency_ms / 1000
            if evaluation_latency_ms is not None
            else None
        ),
        "model": "BRAID",
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
