from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

from .clients import generate


MODEL_NAME = "all-MiniLM-L6-v2"
CASES_ROOT = Path(__file__).parent / "cases"


def load_documents(case_directory):
    case_dir = CASES_ROOT / case_directory
    sources_dir = case_dir / "sources"

    config = {}
    exec(
        (case_dir / "config.py").read_text(encoding="utf-8"),
        config,
    )
    document_ids = config["DOCUMENT_IDS"]

    return [
        (
            document_ids[path.stem],
            path.read_text(encoding="utf-8"),
        )
        for path in sorted(sources_dir.glob("*.md"))
    ]


def retrieve(query, *, case_directory, top_k=5):
    documents = load_documents(case_directory)

    model = SentenceTransformer(MODEL_NAME)
    texts = [text for _, text in documents]

    document_vectors = model.encode(
        texts,
        normalize_embeddings=True,
    )
    query_vector = model.encode(
        query,
        normalize_embeddings=True,
    )

    scores = document_vectors @ np.asarray(query_vector)

    ranked = sorted(
        zip(documents, scores),
        key=lambda item: float(item[1]),
        reverse=True,
    )

    return [
        {
            "source": document[0],
            "score": float(score),
            "text": document[1],
        }
        for document, score in ranked[:top_k]
    ]


async def answer(
    query,
    *,
    case_directory,
    top_k=5,
):
    results = retrieve(
        query,
        case_directory=case_directory,
        top_k=top_k,
    )

    context = "\n\n".join(
        f"Source: {item['source']}\n{item['text']}"
        for item in results
    )

    prompt = f"""Answer the question using the retrieved sources below.

Do not perform any special source-dependency analysis. Treat the retrieved
documents as ordinary RAG context.

Question:

{query}

Retrieved sources:

{context}

Give a concise answer and explain what support in the retrieved sources led
you to it.
"""

    generation = await generate(prompt)

    return {
        "answer": generation["text"],
        "retrieved": results,
        "generation": generation,
    }
