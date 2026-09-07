import pytest

from .cases import (
    source_dependence,
    independent_sources_control,
    retrieve_source_dependence,
)
from ...observations import build_observations, source_ids


def test_source_dependence():
    case = source_dependence()

    assert len(case["documents"]) == 3
    assert len(case["observations"]) == 3

    values = {
        observation.claim.value
        for observation in case["observations"]
    }

    assert values == {3_200_000_000}

    dependent = case["observations"][1:]

    assert all(
        observation.upstream_sources
        for observation in dependent
    )

    assert all(
        observation.parent_assertion_ids
        for observation in dependent
    )


def test_adversarial_retrieval_pool():
    retrieved = retrieve_source_dependence(
        "What was Arm Holdings' total revenue for fiscal 2023?",
        top_k=8,
    )

    assert len(retrieved) == 8

    sources = {
        item["source"]
        for item in retrieved
    }

    assert {
        "false_origin",
        "false_copy_a",
        "false_copy_b",
    }.issubset(sources)

    print("\nADVERSARIAL RETRIEVAL ORDER")
    for index, item in enumerate(retrieved, start=1):
        print(
            f"{index}. {item['source']} "
            f"similarity={item['score']:.6f}"
        )



def test_independent_sources_control():
    from .cases import independent_sources_control

    case = independent_sources_control()

    assert len(case["observations"]) == 3

    assert all(
        not observation.upstream_sources
        for observation in case["observations"]
    )

    assert all(
        not observation.parent_assertion_ids
        for observation in case["observations"]
    )


@pytest.mark.anyio
async def test_dependency_changes_balanced_conflict():
    from .cases import (
        source_dependence,
        independent_sources_control,
    )
    from ...braid_rag import evaluate_context, map_observations
    from ...naive_rag import load_documents
    from ...config import estimator_config

    async def evaluate(adversarial):
        base = build_observations("arm_ipo_2023_revenue")[:3]
        observations = base + adversarial["observations"]

        ids = {
            **source_ids("arm_ipo_2023_revenue"),
            **adversarial["source_ids"],
        }

        documents = dict(load_documents("arm_ipo_2023"))
        documents.update({
            item["source"]: item["text"]
            for item in adversarial["documents"]
        })

        retrieved = [
            {
                "source": ids[observation.source],
                "score": 0.0,
                "text": documents[ids[observation.source]],
            }
            for observation in observations
        ]

        mapped = map_observations(
            retrieved,
            observations,
            ids,
        )

        return await evaluate_context(
            mapped,
            estimator=estimator_config(),
        )

    dependent = await evaluate(
        source_dependence()
    )
    independent = await evaluate(
        independent_sources_control()
    )

    dependent_by_value = {
        claim.claim.value: claim
        for claim in dependent.claim_support
    }
    independent_by_value = {
        claim.claim.value: claim
        for claim in independent.claim_support
    }

    correct = 2_679_000_000
    false = 3_200_000_000

    assert (
        dependent_by_value[correct].support
        > dependent_by_value[false].support
    )

    assert (
        dependent_by_value[false]
        .estimated_independent_support_count
        < independent_by_value[false]
        .estimated_independent_support_count
    )

    assert independent_by_value[correct].support == pytest.approx(
        independent_by_value[false].support
    )

    assert independent_by_value[correct].is_attribute_max_support
    assert independent_by_value[false].is_attribute_max_support


def test_treatment_ground_truth():
    case = source_dependence()

    relationships = {
        (
            observation.assertion_id,
            tuple(observation.parent_assertion_ids),
        )
        for observation in case["observations"]
        if observation.parent_assertion_ids
    }

    assert relationships == {
        (
            "false-copy-a-revenue",
            ("false-origin-revenue",),
        ),
        (
            "false-copy-b-revenue",
            ("false-origin-revenue",),
        ),
    }


def test_independent_ground_truth():
    case = independent_sources_control()

    assert all(
        not observation.upstream_sources
        and not observation.cited_sources
        and not observation.parent_assertion_ids
        for observation in case["observations"]
    )


@pytest.mark.anyio
async def test_sparse_provenance():
    from .cases import sparse_provenance_control
    from ...braid_rag import evaluate_context, map_observations
    from ...naive_rag import load_documents
    from ...config import estimator_config

    async def evaluate(adversarial):
        base = build_observations("arm_ipo_2023_revenue")[:3]
        observations = base + adversarial["observations"]

        ids = {
            **source_ids("arm_ipo_2023_revenue"),
            **adversarial["source_ids"],
        }

        documents = dict(load_documents("arm_ipo_2023"))
        documents.update({
            item["source"]: item["text"]
            for item in adversarial["documents"]
        })

        retrieved = [
            {
                "source": ids[observation.source],
                "score": 0.0,
                "text": documents[ids[observation.source]],
            }
            for observation in observations
        ]

        mapped = map_observations(
            retrieved,
            observations,
            ids,
        )

        return await evaluate_context(
            mapped,
            estimator=estimator_config(),
        )

    full = await evaluate(source_dependence())
    sparse = await evaluate(sparse_provenance_control())
    none = await evaluate(independent_sources_control())

    def false_claim(evaluation):
        return next(
            claim
            for claim in evaluation.claim_support
            if claim.claim.value == 3_200_000_000
        )

    full_false = false_claim(full)
    sparse_false = false_claim(sparse)
    none_false = false_claim(none)

    assert (
        full_false.estimated_independent_support_count
        < sparse_false.estimated_independent_support_count
        < none_false.estimated_independent_support_count
    )

    assert full_false.support < sparse_false.support
    assert sparse_false.support <= none_false.support


@pytest.mark.anyio
async def test_noisy_metadata():
    from .cases import noisy_metadata_control
    from ...braid_rag import evaluate_context, map_observations
    from ...naive_rag import load_documents
    from ...config import estimator_config

    async def evaluate(adversarial):
        base = build_observations("arm_ipo_2023_revenue")[:3]
        observations = base + adversarial["observations"]

        ids = {
            **source_ids("arm_ipo_2023_revenue"),
            **adversarial["source_ids"],
        }

        documents = dict(load_documents("arm_ipo_2023"))
        documents.update({
            item["source"]: item["text"]
            for item in adversarial["documents"]
        })

        retrieved = [
            {
                "source": ids[observation.source],
                "score": 0.0,
                "text": documents[ids[observation.source]],
            }
            for observation in observations
        ]

        mapped = map_observations(
            retrieved,
            observations,
            ids,
        )

        return await evaluate_context(
            mapped,
            estimator=estimator_config(),
        )

    clean = await evaluate(independent_sources_control())
    upstream = await evaluate(
        noisy_metadata_control()
    )
    lineage = await evaluate(
        noisy_metadata_control(lineage=True)
    )

    def false_claim(evaluation):
        return next(
            claim
            for claim in evaluation.claim_support
            if claim.claim.value == 3_200_000_000
        )

    clean_false = false_claim(clean)
    upstream_false = false_claim(upstream)
    lineage_false = false_claim(lineage)

    assert (
        clean_false.estimated_independent_support_count
        > upstream_false.estimated_independent_support_count
        > lineage_false.estimated_independent_support_count
    )

    assert clean_false.support > upstream_false.support
    assert upstream_false.support > lineage_false.support


@pytest.mark.anyio
async def test_semantic_noise():
    from datetime import datetime, timezone

    from omneum import Claim, Observation, Source

    from ...braid_rag import (
        evaluate_context,
        map_observations,
        select_context,
    )
    from ...config import estimator_config

    revenue_source = Source(
        "web_document",
        "https://synthetic.local/arm/revenue",
    )
    distractor_source = Source(
        "web_document",
        "https://synthetic.local/arm/revenue-growth",
    )

    revenue = Claim(
        "service",
        "arm_holdings",
        "FY2023 total revenue",
        2_679_000_000,
    )
    distractor = Claim(
        "service",
        "arm_holdings",
        "FY2023 revenue growth",
        -0.01,
    )

    timestamp = datetime(
        2023,
        8,
        23,
        tzinfo=timezone.utc,
    )

    observations = (
        Observation(
            assertion_id="revenue",
            source=revenue_source,
            claim=revenue,
            observed_at=timestamp,
        ),
        Observation(
            assertion_id="revenue-growth",
            source=distractor_source,
            claim=distractor,
            observed_at=timestamp,
        ),
    )

    ids = {
        revenue_source: "revenue",
        distractor_source: "revenue_growth",
    }

    retrieved = [
        {
            "source": "revenue",
            "score": 0.80,
            "text": (
                "Arm Holdings reported $2.679 billion in total "
                "revenue for fiscal 2023."
            ),
        },
        {
            "source": "revenue_growth",
            "score": 0.95,
            "text": (
                "Arm Holdings fiscal 2023 revenue fell 1 percent "
                "from the prior year."
            ),
        },
    ]

    mapped = map_observations(
        retrieved,
        observations,
        ids,
    )

    evaluation = await evaluate_context(
        mapped,
        estimator=estimator_config(),
    )

    winners = [
        claim
        for claim in evaluation.claim_support
        if claim.is_attribute_max_support
    ]

    selected = select_context(
        mapped,
        evaluation,
        top_n=2,
    )

    assert len(winners) == 2
    assert {
        claim.claim.attribute
        for claim in winners
    } == {
        "fy2023_total_revenue",
        "fy2023_revenue_growth",
    }
    assert {
        item["retrieved"]["source"]
        for item in selected
    } == {
        "revenue",
        "revenue_growth",
    }
