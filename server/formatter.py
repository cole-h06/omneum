# formatter.py

from .types import (
    GraphSummary,
    InferenceMetadata,
    SourceScore,
    ClaimSupport,
)


def build_source_scores(
    credibility: dict[str, float],
) -> list[SourceScore]:
    """
    Convert the internal credibility vector into a sorted
    list of source score objects.
    """

    return [
        SourceScore(
            source_id=source_id,
            credibility=score,
        )
        for source_id, score in sorted(
            credibility.items(),
            key=lambda item: item[1],
            reverse=True,
        )
    ]


def build_claim_support(
    support: dict[str, float],
) -> list[ClaimSupport]:
    """
    Convert claim support values into protocol objects.
    """

    return [
        ClaimSupport(
            claim_id=claim_id,
            support=score,
        )
        for claim_id, score in sorted(
            support.items(),
            key=lambda item: item[1],
            reverse=True,
        )
    ]


def build_summary(
    *,
    source_count: int,
    claim_count: int,
    assertion_count: int,
) -> GraphSummary:
    """
    Build a graph summary.
    """

    return GraphSummary(
        source_count=source_count,
        claim_count=claim_count,
        assertion_count=assertion_count,
    )


def build_metadata(
    *,
    iterations: int,
) -> InferenceMetadata:
    """
    Build inference metadata.
    """

    return InferenceMetadata(
        iterations=iterations,
    )