=from collections import defaultdict

from .models import Assertion
from .types import CredibilityGraph


def build_graph(
    assertions: list[Assertion],
) -> CredibilityGraph:
    """
    Construct the internal credibility graph consumed by the
    inference engine.
    """

    source_to_claims = defaultdict(set)
    claim_to_sources = defaultdict(set)

    claim_to_attribute = {}
    attribute_to_claims = defaultdict(set)

    for assertion in assertions:

        source_to_claims[
            assertion.source_id
        ].add(
            assertion.claim_id
        )

        claim_to_sources[
            assertion.claim_id
        ].add(
            assertion.source_id
        )

        claim_to_attribute[
            assertion.claim_id
        ] = assertion.attribute_id

        attribute_to_claims[
            assertion.attribute_id
        ].add(
            assertion.claim_id
        )

    return CredibilityGraph(
        source_to_claims=dict(source_to_claims),
        claim_to_sources=dict(claim_to_sources),

        claim_to_attribute=claim_to_attribute,
        attribute_to_claims=dict(attribute_to_claims),

        assertion_count=len(assertions),

        agreement_weights={},
    )