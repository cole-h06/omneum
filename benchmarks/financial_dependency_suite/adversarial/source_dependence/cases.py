from datetime import datetime, timezone

from omneum import Claim, Observation, Source, SourceReference

from ...naive_rag import load_documents, rank_documents


FALSE_ORIGIN = Source(
    "web_document",
    "https://synthetic.local/arm-fy2023/false-origin",
)

FALSE_COPY_A = Source(
    "web_document",
    "https://synthetic.local/arm-fy2023/false-copy-a",
)

FALSE_COPY_B = Source(
    "web_document",
    "https://synthetic.local/arm-fy2023/false-copy-b",
)


FALSE_DOCUMENTS = (
    {
        "source": "false_origin",
        "text": (
            "Arm Holdings reported total revenue of $3.2 billion "
            "for fiscal year 2023."
        ),
    },
    {
        "source": "false_copy_a",
        "text": (
            "Arm Holdings generated $3.2 billion in total revenue "
            "during fiscal 2023."
        ),
    },
    {
        "source": "false_copy_b",
        "text": (
            "Arm Holdings' total revenue for fiscal 2023 was "
            "approximately $3.2 billion."
        ),
    },
)


FALSE_SOURCE_IDS = {
    FALSE_ORIGIN: "false_origin",
    FALSE_COPY_A: "false_copy_a",
    FALSE_COPY_B: "false_copy_b",
}


def _reference(source):
    return SourceReference(
        source.kind,
        source.identifier,
    )


def _observation(
    assertion_id,
    source,
    claim,
    *,
    upstream_sources=(),
    parent_assertion_ids=(),
):
    timestamp = datetime(
        2023,
        8,
        23,
        tzinfo=timezone.utc,
    )

    return Observation(
        assertion_id=assertion_id,
        source=source,
        claim=claim,
        observed_at=timestamp,
        source_modified_at=timestamp,
        upstream_sources=tuple(upstream_sources),
        cited_sources=(),
        parent_assertion_ids=tuple(parent_assertion_ids),
        retrievals=(),
    )


def source_dependence():
    claim = Claim(
        "service",
        "arm_holdings",
        "FY2023 total revenue",
        3_200_000_000,
    )

    observations = (
        _observation(
            "false-origin-revenue",
            FALSE_ORIGIN,
            claim,
        ),
        _observation(
            "false-copy-a-revenue",
            FALSE_COPY_A,
            claim,
            upstream_sources=(
                _reference(FALSE_ORIGIN),
            ),
            parent_assertion_ids=(
                "false-origin-revenue",
            ),
        ),
        _observation(
            "false-copy-b-revenue",
            FALSE_COPY_B,
            claim,
            upstream_sources=(
                _reference(FALSE_ORIGIN),
            ),
            parent_assertion_ids=(
                "false-origin-revenue",
            ),
        ),
    )

    return {
        "documents": FALSE_DOCUMENTS,
        "observations": observations,
        "source_ids": FALSE_SOURCE_IDS,
    }


def retrieve_source_dependence(query, *, top_k=5):
    documents = load_documents("arm_ipo_2023")

    adversarial_documents = [
        (document["source"], document["text"])
        for document in FALSE_DOCUMENTS
    ]

    return rank_documents(
        query,
        documents + adversarial_documents,
        top_k=top_k,
    )



def independent_sources_control():
    claim = Claim(
        "service",
        "arm_holdings",
        "FY2023 total revenue",
        3_200_000_000,
    )

    observations = (
        _observation(
            "false-independent-a",
            FALSE_ORIGIN,
            claim,
        ),
        _observation(
            "false-independent-b",
            FALSE_COPY_A,
            claim,
        ),
        _observation(
            "false-independent-c",
            FALSE_COPY_B,
            claim,
        ),
    )

    return {
        "documents": FALSE_DOCUMENTS,
        "observations": observations,
        "source_ids": FALSE_SOURCE_IDS,
    }


def sparse_provenance_control():
    claim = Claim(
        "service",
        "arm_holdings",
        "FY2023 total revenue",
        3_200_000_000,
    )

    observations = (
        _observation(
            "false-origin-revenue",
            FALSE_ORIGIN,
            claim,
        ),
        _observation(
            "false-copy-a-revenue",
            FALSE_COPY_A,
            claim,
            upstream_sources=(
                _reference(FALSE_ORIGIN),
            ),
            parent_assertion_ids=(
                "false-origin-revenue",
            ),
        ),
        _observation(
            "false-copy-b-revenue",
            FALSE_COPY_B,
            claim,
        ),
    )

    return {
        "documents": FALSE_DOCUMENTS,
        "observations": observations,
        "source_ids": FALSE_SOURCE_IDS,
    }


def noisy_metadata_control(*, lineage=False):
    claim = Claim(
        "service",
        "arm_holdings",
        "FY2023 total revenue",
        3_200_000_000,
    )

    parent_ids = (
        ("false-origin-revenue",)
        if lineage
        else ()
    )

    observations = (
        _observation(
            "false-origin-revenue",
            FALSE_ORIGIN,
            claim,
        ),
        _observation(
            "false-copy-a-revenue",
            FALSE_COPY_A,
            claim,
            upstream_sources=(
                _reference(FALSE_ORIGIN),
            ),
            parent_assertion_ids=parent_ids,
        ),
        _observation(
            "false-copy-b-revenue",
            FALSE_COPY_B,
            claim,
            upstream_sources=(
                _reference(FALSE_ORIGIN),
            ),
            parent_assertion_ids=parent_ids,
        ),
    )

    return {
        "documents": FALSE_DOCUMENTS,
        "observations": observations,
        "source_ids": FALSE_SOURCE_IDS,
    }
