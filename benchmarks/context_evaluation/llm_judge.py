import json

from .clients import generate
from .naive_rag import retrieve


async def judge_dependencies_from_results(
    query,
    results,
    *,
    provider=None,
    model=None,
    include_text=True,
):
    context_parts = []

    for item in results:
        part = f"Source ID: {item['source']}"

        if include_text:
            part += f"\n{item['text']}"

        metadata = item.get("metadata")
        if metadata:
            part += (
                "\n\nSource metadata:\n"
                + json.dumps(metadata, indent=2)
            )

        context_parts.append(part)

    context = "\n\n".join(context_parts)

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

    generation = await generate(
        prompt,
        provider=provider,
        model=model,
    )
    text = generation["text"].strip()

    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]

        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

        text = "\n".join(lines).strip()

    try:
        data = json.loads(text)
        relationships = data["relationships"]

        if not isinstance(relationships, list):
            raise ValueError("relationships must be a list")

        source_ids = {item["source"] for item in results}

        for relationship in relationships:
            if not isinstance(relationship, dict):
                raise ValueError("relationship must be an object")

            source = relationship["source"]
            depends_on = relationship["depends_on"]
            relationship_type = relationship["relationship_type"]
            confidence = relationship["confidence"]

            if source not in source_ids or depends_on not in source_ids:
                raise ValueError("relationship contains unknown source")

            if source == depends_on:
                raise ValueError("source cannot depend on itself")

            if not isinstance(relationship_type, str):
                raise ValueError("relationship_type must be a string")

            if (
                isinstance(confidence, bool)
                or not isinstance(confidence, (int, float))
                or not 0.0 <= confidence <= 1.0
            ):
                raise ValueError("confidence must be between 0 and 1")

        parse_error = None
    except (
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        relationships = None
        parse_error = str(exc)

    return {
        "relationships": relationships,
        "parse_error": parse_error,
        "generation": generation,
        "retrieved": results,
    }


async def judge_dependencies(
    query,
    *,
    case_directory,
    top_k=5,
    provider=None,
    model=None,
):
    results = retrieve(
        query,
        case_directory=case_directory,
        top_k=top_k,
    )

    return await judge_dependencies_from_results(
        query,
        results,
        provider=provider,
        model=model,
    )
