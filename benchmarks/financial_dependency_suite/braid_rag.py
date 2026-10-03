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


def select_context(mapped, evaluation, *, top_n):
    mapped_by_source = {
        item["observation"].source: item
        for item in mapped
    }

    winning_claims = [
        claim
        for claim in evaluation.claim_support
        if claim.is_attribute_max_support
    ]

    queues = []

    for claim in winning_claims:
        supporters = [
            {
                **mapped_by_source[supporter.source],
                "claim": claim.claim,
                "claim_support": claim.support,
                "braid_contribution": supporter.contribution,
            }
            for supporter in claim.supporting_sources
            if supporter.source in mapped_by_source
        ]

        if supporters:
            queues.append(supporters)

    selected = []
    selected_sources = set()

    while queues and len(selected) < top_n:
        remaining = []

        for queue in queues:
            while queue:
                item = queue.pop(0)
                source = item["observation"].source

                if source not in selected_sources:
                    selected.append(item)
                    selected_sources.add(source)
                    break

            if queue:
                remaining.append(queue)

            if len(selected) >= top_n:
                break

        queues = remaining

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

