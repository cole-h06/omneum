from .clients import generate


async def answer_from_context(
    query,
    documents,
    *,
    provider=None,
    model=None,
):
    context = "\n\n".join(
        f"Source: {item['source']}\n{item['text']}"
        for item in documents
    )

    prompt = f"""Answer the question using only the sources below.

Question:

{query}

Sources:

{context}

Give a concise answer and identify which sources support it.
"""

    return await generate(
        prompt,
        provider=provider,
        model=model,
    )
