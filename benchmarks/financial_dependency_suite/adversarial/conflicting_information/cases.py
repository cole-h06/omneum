from datetime import datetime, timezone

from omneum import Claim, Observation, Source


CORRECT_VALUE = (
    "EY concluded that it could no longer rely on representations "
    "from management and the Audit Committee and was unwilling to "
    "be associated with management's financial statements."
)

FALSE_VALUE = (
    "EY resigned because of a commercial disagreement with "
    "Super Micro Computer over audit fees."
)


CORRECT_SOURCES = (
    Source("web_document", "https://synthetic.local/smci/correct-a"),
    Source("web_document", "https://synthetic.local/smci/correct-b"),
    Source("web_document", "https://synthetic.local/smci/correct-c"),
)

FALSE_SOURCES = (
    Source("web_document", "https://synthetic.local/smci/false-a"),
    Source("web_document", "https://synthetic.local/smci/false-b"),
    Source("web_document", "https://synthetic.local/smci/false-c"),
)


SOURCE_IDS = {
    CORRECT_SOURCES[0]: "source_a",
    CORRECT_SOURCES[1]: "source_b",
    CORRECT_SOURCES[2]: "source_c",
    FALSE_SOURCES[0]: "source_d",
    FALSE_SOURCES[1]: "source_e",
    FALSE_SOURCES[2]: "source_f",
}


DOCUMENTS = (
    {
        "source": "source_a",
        "text": (
            "EY said it could no longer rely on representations "
            "from Super Micro Computer management and the Audit "
            "Committee."
        ),
    },
    {
        "source": "source_b",
        "text": (
            "EY resigned after concluding that management and Audit "
            "Committee representations could no longer be relied on."
        ),
    },
    {
        "source": "source_c",
        "text": (
            "EY said it was unwilling to remain associated with "
            "management's financial statements."
        ),
    },
    {
        "source": "source_d",
        "text": (
            "EY resigned as Super Micro Computer's auditor because "
            "of a commercial disagreement over audit fees."
        ),
    },
    {
        "source": "source_e",
        "text": (
            "The auditor departure resulted from a dispute with "
            "Super Micro Computer concerning audit fees."
        ),
    },
    {
        "source": "source_f",
        "text": (
            "A disagreement over audit fees led EY to end its "
            "relationship with Super Micro Computer."
        ),
    },
)


def observation(assertion_id, source, claim):
    timestamp = datetime(
        2024,
        10,
        30,
        tzinfo=timezone.utc,
    )

    return Observation(
        observation_id=assertion_id,
        source=source,
        claim=claim,
        observed_at=timestamp,
        source_modified_at=timestamp,
        upstream_sources=(),
        cited_sources=(),
        parent_observation_ids=(),
        retrievals=(),
    )


def target_observations():
    correct = Claim(
        "service",
        "super_micro_computer",
        "auditor resignation reason",
        CORRECT_VALUE,
    )
    false = Claim(
        "service",
        "super_micro_computer",
        "auditor resignation reason",
        FALSE_VALUE,
    )

    observations = []

    for index, source in enumerate(CORRECT_SOURCES):
        observations.append(
            observation(
                f"correct-target-{index}",
                source,
                correct,
            )
        )

    for index, source in enumerate(FALSE_SOURCES):
        observations.append(
            observation(
                f"false-target-{index}",
                source,
                false,
            )
        )

    return tuple(observations)


def supporting_observations():
    observations = []

    attributes = (
        ("filing_status", "filed", "not_filed"),
        ("audit_committee_response", "initiated_review", "no_review"),
        ("auditor_status", "resigned", "remained"),
    )

    for number, (attribute, correct_value, false_value) in enumerate(
        attributes
    ):
        correct = Claim(
            "service",
            "super_micro_computer",
            attribute,
            correct_value,
        )
        false = Claim(
            "service",
            "super_micro_computer",
            attribute,
            false_value,
        )

        for index, source in enumerate(CORRECT_SOURCES):
            observations.append(
                observation(
                    f"correct-{number}-{index}",
                    source,
                    correct,
                )
            )

        observations.append(
            observation(
                f"false-{number}",
                FALSE_SOURCES[number],
                false,
            )
        )

    return tuple(observations)


def conflict():
    return {
        "documents": DOCUMENTS,
        "observations": (
            target_observations()
            + supporting_observations()
        ),
        "source_ids": SOURCE_IDS,
    }


def balanced_control():
    return {
        "documents": DOCUMENTS,
        "observations": target_observations(),
        "source_ids": SOURCE_IDS,
    }
