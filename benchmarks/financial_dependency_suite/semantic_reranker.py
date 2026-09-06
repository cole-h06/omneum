import os
from functools import lru_cache
from time import perf_counter

import cohere
from sentence_transformers import CrossEncoder


BGE_MODEL = "BAAI/bge-reranker-v2-m3"
COHERE_MODEL = "rerank-v4.0-pro"


@lru_cache(maxsize=1)
def bge_model():
    return CrossEncoder(BGE_MODEL)


def rerank_bge(query, candidates, *, top_n):
    if top_n < 1:
        raise ValueError("top_n must be at least 1")

    if not candidates:
        return []

    pairs = [
        (query, candidate["text"])
        for candidate in candidates
    ]

    scores = bge_model().predict(pairs)

    ranked = sorted(
        zip(candidates, scores),
        key=lambda item: float(item[1]),
        reverse=True,
    )

    return [
        {
            **candidate,
            "reranker_score": float(score),
        }
        for candidate, score in ranked[:top_n]
    ]


def rerank_cohere(query, candidates, *, top_n):
    if top_n < 1:
        raise ValueError("top_n must be at least 1")

    if not candidates:
        return {
            "selected": [],
            "model": COHERE_MODEL,
            "latency_seconds": 0.0,
        }

    api_key = os.environ.get("COHERE_API_KEY")
    if not api_key:
        raise RuntimeError("COHERE_API_KEY is not set")

    client = cohere.ClientV2(api_key=api_key)

    started = perf_counter()

    response = client.rerank(
        model=COHERE_MODEL,
        query=query,
        documents=[
            candidate["text"]
            for candidate in candidates
        ],
        top_n=min(top_n, len(candidates)),
    )

    latency_seconds = perf_counter() - started

    selected = [
        {
            **candidates[result.index],
            "reranker_score": float(result.relevance_score),
        }
        for result in response.results
    ]

    return {
        "selected": selected,
        "model": COHERE_MODEL,
        "latency_seconds": latency_seconds,
    }
