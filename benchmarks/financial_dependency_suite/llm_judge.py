import json

from .clients import generate
from .naive_rag import retrieve


async def judge_dependencies(
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
        f"Source ID: {item['source']}\n{item['text']}"
        for item in results
    )

    prompt = f"""Determine whether any retrieved source depends on another retrieved source
for the information relevant to the question.

Count as dependency:
- explicit citation or attribution
- syndication or republication
- one source explicitly deriving the relevant information from another
- documented upstream/downstream reporting relationships

Do not infer dependency merely because:
- two sources report the same fact
- publication times are close
- wording is similar without sufficient support

For every detected relationship, return:
- source
- depends_on
- relationship_type
- confidence

Return only relationships supported by the supplied documents.

Return JSON only in this format:

{{
  "relationships": [
    {{
      "source": "source_id",
      "depends_on": "source_id",
      "relationship_type": "relationship",
      "confidence": 0.0
    }}
  ]
}}

Question:

{query}

Sources:

{context}
"""

    generation = await generate(prompt)
    text = generation["text"].strip()

    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1])

    data = json.loads(text)

    return {
        "relationships": data["relationships"],
        "generation": generation,
        "retrieved": results,
    }
