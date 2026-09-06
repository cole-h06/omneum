import pytest

from .cases import (
    source_dependence,
    independent_sources_control,
    retrieve_source_dependence,
)


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
    from ...observations import build_observations, source_ids
    from ...run_suite import estimator_config

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
