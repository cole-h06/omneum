from datetime import datetime, timezone

from omneum import Claim, Observation, Source, SourceReference


SCOPE = "12345678-1234-4abc-8def-123456789abc"


def _source(object_id):
    return Source(
        "internal_resource",
        f"v1:{SCOPE}:{object_id}",
    )


CIRCULAR_A = _source(
    "11111111-1111-4111-8111-111111111111"
)
CIRCULAR_B = _source(
    "22222222-2222-4222-8222-222222222222"
)
CIRCULAR_C = _source(
    "33333333-3333-4333-8333-333333333333"
)

INDEPENDENT_A = _source(
    "44444444-4444-4444-8444-444444444444"
)
INDEPENDENT_B = _source(
    "55555555-5555-4555-8555-555555555555"
)
INDEPENDENT_C = _source(
    "66666666-6666-4666-8666-666666666666"
)


CIRCULAR_CLAIM = Claim(
    "service",
    "payments-api",
    "request timeout",
    30,
)

INDEPENDENT_CLAIM = Claim(
    "service",
    "payments-api",
    "request timeout",
    60,
)


SOURCE_IDS = {
    CIRCULAR_A: "circular_a",
    CIRCULAR_B: "circular_b",
    CIRCULAR_C: "circular_c",
    INDEPENDENT_A: "independent_a",
    INDEPENDENT_B: "independent_b",
    INDEPENDENT_C: "independent_c",
}


DOCUMENTS = tuple(
    {
        "source": source_id,
        "text": (
            f"The payments-api request timeout is "
            f"{30 if source_id.startswith('circular') else 60} "
            f"seconds."
        ),
    }
    for source_id in SOURCE_IDS.values()
)


def _reference(source):
    return SourceReference(
        source.kind,
        source.identifier,
    )


def _timestamp(date):
    return datetime.fromisoformat(date).replace(
        tzinfo=timezone.utc
    )


def _observation(
    assertion_id,
    source,
    claim,
    date,
    *,
    upstream_sources=(),
    parent_assertion_ids=(),
):
    timestamp = _timestamp(date)

    return Observation(
        observation_id=assertion_id,
        source=source,
        claim=claim,
        observed_at=timestamp,
        source_modified_at=timestamp,
        upstream_sources=tuple(upstream_sources),
        cited_sources=(),
        parent_observation_ids=tuple(parent_assertion_ids),
        retrievals=(),
    )


def circular_sources():
    observations = (
        _observation(
            "circular-a",
            CIRCULAR_A,
            CIRCULAR_CLAIM,
            "2026-08-01",
            upstream_sources=(
                _reference(CIRCULAR_C),
            ),
            parent_assertion_ids=("circular-c",),
        ),
        _observation(
            "circular-b",
            CIRCULAR_B,
            CIRCULAR_CLAIM,
            "2026-08-10",
            upstream_sources=(
                _reference(CIRCULAR_A),
            ),
            parent_assertion_ids=("circular-a",),
        ),
        _observation(
            "circular-c",
            CIRCULAR_C,
            CIRCULAR_CLAIM,
            "2026-08-20",
            upstream_sources=(
                _reference(CIRCULAR_B),
            ),
            parent_assertion_ids=("circular-b",),
        ),
        _observation(
            "independent-a",
            INDEPENDENT_A,
            INDEPENDENT_CLAIM,
            "2026-07-01",
        ),
        _observation(
            "independent-b",
            INDEPENDENT_B,
            INDEPENDENT_CLAIM,
            "2026-07-10",
        ),
        _observation(
            "independent-c",
            INDEPENDENT_C,
            INDEPENDENT_CLAIM,
            "2026-07-20",
        ),
    )

    return {
        "documents": DOCUMENTS,
        "observations": observations,
        "source_ids": SOURCE_IDS,
    }


def independent_sources_control():
    observations = (
        _observation(
            "control-a",
            CIRCULAR_A,
            CIRCULAR_CLAIM,
            "2026-08-01",
        ),
        _observation(
            "control-b",
            CIRCULAR_B,
            CIRCULAR_CLAIM,
            "2026-08-10",
        ),
        _observation(
            "control-c",
            CIRCULAR_C,
            CIRCULAR_CLAIM,
            "2026-08-20",
        ),
        _observation(
            "independent-a",
            INDEPENDENT_A,
            INDEPENDENT_CLAIM,
            "2026-07-01",
        ),
        _observation(
            "independent-b",
            INDEPENDENT_B,
            INDEPENDENT_CLAIM,
            "2026-07-10",
        ),
        _observation(
            "independent-c",
            INDEPENDENT_C,
            INDEPENDENT_CLAIM,
            "2026-07-20",
        ),
    )

    return {
        "documents": DOCUMENTS,
        "observations": observations,
        "source_ids": SOURCE_IDS,
    }


def acyclic_dependency_chain():
    observations = (
        _observation(
            "chain-a",
            CIRCULAR_A,
            CIRCULAR_CLAIM,
            "2026-08-01",
        ),
        _observation(
            "chain-b",
            CIRCULAR_B,
            CIRCULAR_CLAIM,
            "2026-08-10",
            upstream_sources=(
                _reference(CIRCULAR_A),
            ),
            parent_assertion_ids=("chain-a",),
        ),
        _observation(
            "chain-c",
            CIRCULAR_C,
            CIRCULAR_CLAIM,
            "2026-08-20",
            upstream_sources=(
                _reference(CIRCULAR_B),
            ),
            parent_assertion_ids=("chain-b",),
        ),
        _observation(
            "independent-a",
            INDEPENDENT_A,
            INDEPENDENT_CLAIM,
            "2026-07-01",
        ),
        _observation(
            "independent-b",
            INDEPENDENT_B,
            INDEPENDENT_CLAIM,
            "2026-07-10",
        ),
        _observation(
            "independent-c",
            INDEPENDENT_C,
            INDEPENDENT_CLAIM,
            "2026-07-20",
        ),
    )

    return {
        "documents": DOCUMENTS,
        "observations": observations,
        "source_ids": SOURCE_IDS,
    }
