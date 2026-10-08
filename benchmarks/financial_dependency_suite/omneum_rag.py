from omneum import open_stdio_client

from .generation import answer_from_context

from .deployment import benchmark_deployment


def map_observations(retrieved, observations, source_ids):
    observations_by_source = {
        source_ids[observation.source]: observation
        for observation in observations
    }

    return [
        {
            "retrieved": item,
            "observation": observations_by_source[item["source"]],
        }
        for item in retrieved
    ]


async def evaluate_context(mapped, *, estimator):
    observations = tuple(
        item["observation"]
        for item in mapped
    )

    with benchmark_deployment() as (config, server):
        async with open_stdio_client(config, server) as client:
            return await client.evaluate_context(
                observations,
                estimator=estimator,
            )


def select_context(query, mapped, evaluation, *, top_n):
    mapped_by_source = {
        item["observation"].source: item
        for item in mapped
    }

    # Query relevance over the same candidate set evaluated by Omneum.
    from .naive_rag import rank_documents

    documents = [
        (
            item["retrieved"]["source"],
            item["retrieved"]["text"],
        )
        for item in mapped
    ]

    relevance = {
        item["source"]: item["score"]
        for item in rank_documents(
            query,
            documents,
            top_k=len(documents),
        )
    }

    candidates = []

    # Do not discard competing claims. Omneum evaluates their structural
    # support; query relevance determines which claims matter to this query.
    for claim in evaluation.claim_support:
        for supporter in claim.supporting_sources:
            mapped_item = mapped_by_source.get(supporter.source)

            if mapped_item is None:
                continue

            source = mapped_item["retrieved"]["source"]

            candidates.append({
                **mapped_item,
                "claim": claim.claim,
                "claim_support": claim.support,
                "omneum_contribution": supporter.contribution,
                "relevance": relevance.get(source, 0.0),
            })

    # Normalize structural quantities so their raw scales do not dominate
    # query relevance.
    max_support = max(
        (item["claim_support"] for item in candidates),
        default=1.0,
    )
    max_contribution = max(
        (item["omneum_contribution"] for item in candidates),
        default=1.0,
    )

    for item in candidates:
        support = (
            item["claim_support"] / max_support
            if max_support
            else 0.0
        )
        contribution = (
            item["omneum_contribution"] / max_contribution
            if max_contribution
            else 0.0
        )

        structural = 0.5 * support + 0.5 * contribution

        item["selection_score"] = (
            0.6 * item["relevance"]
            + 0.4 * structural
        )

    candidates.sort(
        key=lambda item: item["selection_score"],
        reverse=True,
    )

    selected = []
    selected_sources = set()

    for item in candidates:
        source = item["observation"].source

        if source in selected_sources:
            continue

        selected.append(item)
        selected_sources.add(source)

        if len(selected) >= top_n:
            break

    return selected


def select_reliable_context(mapped, evaluation, *, top_n):
    """Select context supporting structurally preferred claims, ranked by relevance and reliability."""
    def source_key(source):
        if hasattr(source, "kind") and hasattr(source, "identifier"):
            return (source.kind, source.identifier)
        return source

    reliability = {
        source_key(result.source): result.reliability
        for result in evaluation.source_reliability
    }

    max_claims = [
        claim
        for claim in evaluation.claim_support
        if claim.is_attribute_max_support
    ]

    # Structural ties leave every tied claim eligible for context selection.
    winning_sources = {
        source_key(supporter.source)
        for claim in max_claims
        for supporter in claim.supporting_sources
    }

    eligible_sources = winning_sources or {
        source_key(item["observation"].source)
        for item in mapped
    }

    candidates = []
    seen = set()

    for index, item in enumerate(mapped):
        source = source_key(item["observation"].source)
        if source in seen or source not in eligible_sources:
            continue
        seen.add(source)

        relevance = item["retrieved"].get("reranker_score")
        if relevance is None:
            relevance = 1.0

        quality = reliability.get(source, 1.0)
        candidates.append((relevance * quality, index, source, item))

    candidates.sort(key=lambda row: (-row[0], row[1]))

    selected = []

    for _, _, _, item in candidates:
        selected.append(item)

        if len(selected) >= top_n:
            break

    return selected


async def answer(
    query,
    *,
    case_directory,
    observations,
    source_ids,
    estimator,
    top_k=5,
    top_n=3,
):
    from .naive_rag import retrieve

    retrieved = retrieve(
        query,
        case_directory=case_directory,
        top_k=top_k,
    )

    mapped = map_observations(
        retrieved,
        observations,
        source_ids,
    )

    evaluation = await evaluate_context(
        mapped,
        estimator=estimator,
    )

    selected = select_context(
        QUERY,
        mapped,
        evaluation,
        top_n=top_n,
    )

    documents = [
        {
            "source": item["retrieved"]["source"],
            "text": item["retrieved"]["text"],
        }
        for item in selected
    ]

    generation = await answer_from_context(
        query,
        documents,
    )

    return {
        "answer": generation["text"],
        "retrieved": retrieved,
        "selected": selected,
        "evaluation": evaluation,
        "generation": generation,
    }
