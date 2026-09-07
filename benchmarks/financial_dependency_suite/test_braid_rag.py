from .braid_rag import (
    evaluate_context,
    map_observations,
    select_context,
)
from .naive_rag import retrieve
from .observations import build_observations, source_ids


def test_maps_observations():
    retrieved = retrieve(
        "What was Arm's FY2023 total revenue?",
        case_directory="arm_ipo_2023",
        top_k=5,
    )

    observations = build_observations("arm_ipo_2023_revenue")
    ids = source_ids("arm_ipo_2023_revenue")

    mapped = map_observations(
        retrieved,
        observations,
        ids,
    )

    assert len(mapped) == len(retrieved)

    for item in mapped:
        assert item["retrieved"]["source"]
        assert item["observation"] in observations

import pytest

from .config import estimator_config


@pytest.mark.anyio
async def test_evaluates_context():
    retrieved = retrieve(
        "What was Arm's FY2023 total revenue?",
        case_directory="arm_ipo_2023",
        top_k=5,
    )

    observations = build_observations("arm_ipo_2023_revenue")
    ids = source_ids("arm_ipo_2023_revenue")

    mapped = map_observations(
        retrieved,
        observations,
        ids,
    )

    result = await evaluate_context(
        mapped,
        estimator=estimator_config(),
    )

    assert result.claim_support
    assert result.source_reliability


@pytest.mark.anyio
async def test_prints_braid_evaluation():
    retrieved = retrieve(
        "What was Arm Holdings' total revenue for fiscal 2023?",
        case_directory="arm_ipo_2023",
        top_k=5,
    )

    observations = build_observations("arm_ipo_2023_revenue")
    ids = source_ids("arm_ipo_2023_revenue")

    mapped = map_observations(
        retrieved,
        observations,
        ids,
    )

    result = await evaluate_context(
        mapped,
        estimator=estimator_config(),
    )

    print("\nSOURCE RELIABILITY")
    for source in result.source_reliability:
        print(source)

    print("\nCLAIM SUPPORT")
    for claim in result.claim_support:
        print(claim)

    print("\nPAIRWISE DEPENDENCIES")
    for pair in result.pairwise_dependencies:
        if pair.dependency <= 0.0:
            continue

        s = pair.signals

        print(
            f"{pair.source_a.identifier} <-> {pair.source_b.identifier}"
            f"  dependency={pair.dependency:.3f}"
            f"  coverage={pair.weighted_signal_coverage:.3f}"
        )
        print(
            f"    upstream={s.upstream:.3f}"
            f" citation={s.citation:.3f}"
            f" assertion_lineage={s.assertion_lineage:.3f}"
            f" ownership={s.ownership:.3f}"
            f" temporal={s.temporal:.3f}"
            f" graph={s.graph:.3f}"
            f" retrieval={s.retrieval:.3f}"
        )


@pytest.mark.anyio
async def test_braid_reranking():
    retrieved = retrieve(
        "What was Arm Holdings' total revenue for fiscal 2023?",
        case_directory="arm_ipo_2023",
        top_k=5,
    )

    observations = build_observations("arm_ipo_2023_revenue")
    ids = source_ids("arm_ipo_2023_revenue")

    mapped = map_observations(
        retrieved,
        observations,
        ids,
    )

    evaluation = await evaluate_context(
        mapped,
        estimator=estimator_config(),
    )

    reranked = select_context(
        mapped,
        evaluation,
        top_n=3,
    )

    assert len(reranked) == 3

    contributions = [
        item["braid_contribution"]
        for item in reranked
    ]

    assert contributions == sorted(
        contributions,
        reverse=True,
    )

    print("\nBRAID TOP 3")
    for item in reranked:
        print(
            item["retrieved"]["source"],
            f"contribution={item['braid_contribution']:.6f}",
        )



@pytest.mark.anyio
async def test_syndicated_source():
    retrieved = retrieve(
        "What was Arm Holdings' total revenue for fiscal 2023?",
        case_directory="arm_ipo_2023",
        top_k=5,
    )

    observations = build_observations("arm_ipo_2023_revenue")
    ids = source_ids("arm_ipo_2023_revenue")

    mapped = map_observations(
        retrieved,
        observations,
        ids,
    )

    result = await evaluate_context(
        mapped,
        estimator=estimator_config(),
    )

    pair = next(
        pair
        for pair in result.pairwise_dependencies
        if {
            pair.source_a.identifier,
            pair.source_b.identifier,
        } == {
            next(
                source.identifier
                for source, source_id in ids.items()
                if source_id == "reuters_pre_filing"
            ),
            next(
                source.identifier
                for source, source_id in ids.items()
                if source_id
                == "communications_today_syndication"
            ),
        }
    )

    claim = result.claim_support[0]

    assert pair.dependency > 0.0
    assert pair.signals.upstream == 1.0
    assert pair.signals.assertion_lineage == 1.0
    assert claim.estimated_independent_support_count < 5.0
