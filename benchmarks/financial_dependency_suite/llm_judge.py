import json

from .clients import generate
from .naive_rag import retrieve


async def judge_dependencies(query, *, top_k=5):
    results = retrieve(query, top_k=top_k)

    context = "\n\n".join(
        (
            f"Source ID: {item['source']}\n"
            f"Retrieval similarity score: {item['score']:.4f}\n"
            f"Document:\n{item['text']}"
        )
        for item in results
    )

    prompt = f"""You are evaluating source dependency within retrieved context.

Determine whether any retrieved source depends on another retrieved source
for the information relevant to the question.

Count as dependency when the supplied information supports:
- explicit citation or attribution
- syndication or republication
- one source deriving the relevant information from another
- an upstream/downstream reporting relationship

Do not infer dependency merely because:
- two sources report the same fact
- publication times are close
- wording is similar without sufficient support

Use the document text and ordinary retrieval metadata supplied below.
Do not assume access to hidden provenance, lineage, or external information.

For every detected relationship, return:
- source
- depends_on
- relationship_type
- confidence

Use only the Source IDs provided below.

Return JSON only in this format:

{{
  "relationships": [
    {{
      "source": "source_id",
      "depends_on": "source_id",
      "relationship_type": "citation | syndication | derivation | upstream",
      "confidence": 0.0
    }}
  ]
}}

If no supported dependency relationships exist, return:

{{
  "relationships": []
}}

Question:
{query}

Retrieved context:
{context}
"""

    generation = await generate(prompt)
    data = json.loads(generation["text"])

    return {
        "relationships": data["relationships"],
        "generation": generation,
        "retrieved": results,
    }