from datetime import datetime, timezone

from omneum import Claim, Observation, Source, SourceReference


STALE_ORIGIN = Source(
    "internal_resource",
    "v1:12345678-1234-4abc-8def-123456789abc:"
    "11111111-1111-4111-8111-111111111111",
)
STALE_COPY_A = Source(
    "internal_resource",
    "v1:12345678-1234-4abc-8def-123456789abc:"
    "22222222-2222-4222-8222-222222222222",
)
STALE_COPY_B = Source(
    "internal_resource",
    "v1:12345678-1234-4abc-8def-123456789abc:"
    "33333333-3333-4333-8333-333333333333",
)

CURRENT_A = Source(
    "internal_resource",
    "v1:12345678-1234-4abc-8def-123456789abc:"
    "44444444-4444-4444-8444-444444444444",
)
CURRENT_B = Source(
    "internal_resource",
    "v1:12345678-1234-4abc-8def-123456789abc:"
    "55555555-5555-4555-8555-555555555555",
)
CURRENT_C = Source(
    "internal_resource",
    "v1:12345678-1234-4abc-8def-123456789abc:"
    "66666666-6666-4666-8666-666666666666",
)


STALE_CLAIM = Claim(
    "service",
    "payments-api",
    "retention period",
    30,
)

CURRENT_CLAIM = Claim(
    "service",
    "payments-api",
    "retention period",
    90,
)


SOURCE_IDS = {
    STALE_ORIGIN: "stale_origin",
    STALE_COPY_A: "stale_copy_a",
    STALE_COPY_B: "stale_copy_b",
    CURRENT_A: "current_a",
    CURRENT_B: "current_b",
    CURRENT_C: "current_c",
}


DOCUMENTS = (
    {
        "source": "stale_origin",
        "text": (
            "The payments-api retention period is 30 days."
        ),
    },
    {
        "source": "stale_copy_a",
        "text": (
            "The configured retention period for payments-api "
            "is 30 days."
        ),
    },
    {
        "source": "stale_copy_b",
        "text": (
            "payments-api retains data for 30 days."
        ),
    },
    {
        "source": "current_a",
        "text": (
            "The payments-api retention period is currently "
            "90 days."
        ),
    },
    {
        "source": "current_b",
        "text": (
            "The current configured retention period for "
            "payments-api is 90 days."
        ),
    },
    {
        "source": "current_c",
        "text": (
            "payments-api currently retains data for 90 days."
        ),
    },
)


def _reference(source):
    return SourceReference(
        source.kind,
        source.identifier,
    )


def _timestamp(value):
    return datetime.fromisoformat(value).replace(
        tzinfo=timezone.utc
    )


def _observation(
    assertion_id,
    source,
    claim,
    *,
    observed_at,
    source_modified_at,
    upstream_sources=(),
    parent_assertion_ids=(),
):
    return Observation(
        observation_id=assertion_id,
        source=source,
        claim=claim,
        observed_at=_timestamp(observed_at),
        source_modified_at=_timestamp(source_modified_at),
        upstream_sources=tuple(upstream_sources),
        cited_sources=(),
        parent_observation_ids=tuple(parent_assertion_ids),
        retrievals=(),
    )


def dependent_stale_data():
    observations = (
        _observation(
            "stale-origin",
            STALE_ORIGIN,
            STALE_CLAIM,
            observed_at="2026-08-01",
            source_modified_at="2026-05-01",
        ),
        _observation(
            "stale-copy-a",
            STALE_COPY_A,
            STALE_CLAIM,
            observed_at="2026-08-01",
            source_modified_at="2026-07-30",
            upstream_sources=(
                _reference(STALE_ORIGIN),
            ),
            parent_assertion_ids=("stale-origin",),
        ),
        _observation(
            "stale-copy-b",
            STALE_COPY_B,
            STALE_CLAIM,
            observed_at="2026-08-01",
            source_modified_at="2026-07-31",
            upstream_sources=(
                _reference(STALE_COPY_A),
            ),
            parent_assertion_ids=("stale-copy-a",),
        ),
        _observation(
            "current-a",
            CURRENT_A,
            CURRENT_CLAIM,
            observed_at="2026-08-01",
            source_modified_at="2026-07-29",
        ),
        _observation(
            "current-b",
            CURRENT_B,
            CURRENT_CLAIM,
            observed_at="2026-08-01",
            source_modified_at="2026-07-29",
        ),
        _observation(
            "current-c",
            CURRENT_C,
            CURRENT_CLAIM,
            observed_at="2026-08-01",
            source_modified_at="2026-07-29",
        ),
    )

    return {
        "documents": DOCUMENTS,
        "observations": observations,
        "source_ids": SOURCE_IDS,
        "ground_truth": 90,
    }


def independent_stale_data():
    observations = (
        _observation(
            "stale-independent-a",
            STALE_ORIGIN,
            STALE_CLAIM,
            observed_at="2026-08-01",
            source_modified_at="2026-05-01",
        ),
        _observation(
            "stale-independent-b",
            STALE_COPY_A,
            STALE_CLAIM,
            observed_at="2026-08-01",
            source_modified_at="2026-05-10",
        ),
        _observation(
            "stale-independent-c",
            STALE_COPY_B,
            STALE_CLAIM,
            observed_at="2026-08-01",
            source_modified_at="2026-05-20",
        ),
        _observation(
            "current-a",
            CURRENT_A,
            CURRENT_CLAIM,
            observed_at="2026-08-01",
            source_modified_at="2026-07-29",
        ),
        _observation(
            "current-b",
            CURRENT_B,
            CURRENT_CLAIM,
            observed_at="2026-08-01",
            source_modified_at="2026-07-29",
        ),
        _observation(
            "current-c",
            CURRENT_C,
            CURRENT_CLAIM,
            observed_at="2026-08-01",
            source_modified_at="2026-07-29",
        ),
    )

    return {
        "documents": DOCUMENTS,
        "observations": observations,
        "source_ids": SOURCE_IDS,
        "ground_truth": 90,
    }
