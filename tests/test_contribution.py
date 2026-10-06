import pytest
from pydantic import ValidationError

from omneum.contribution import (
    ContributionClaim,
    ContributionSource,
    EvaluationContribution,
)


def minimal_contribution(**overrides):
    values = {
        "idempotency_key": "test-evaluation-1",
        "evaluator_version": "omneum-v2",
        "estimator_version": "dependency-estimator-v4",
        "sources": (
            ContributionSource(
                source_id="source-1",
                source_token="opaque-source-token",
                source_kind="web_document",
                key_version=1,
            ),
        ),
        "claims": (
            ContributionClaim(
                claim_id="claim-1",
                claim_token="opaque-claim-token",
                key_version=1,
            ),
        ),
        "observations": (),
        "source_scores": (),
        "claim_scores": (),
        "dependencies": (),
    }
    values.update(overrides)
    return EvaluationContribution(**values)


def test_contribution_accepts_structural_data():
    contribution = minimal_contribution()

    assert contribution.schema_version == "1"
    assert contribution.sources[0].source_kind == "web_document"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("claim_value", "Arm revenue was $2.68B"),
        ("source_url", "https://example.com/private"),
        ("retrieved_text", "private context"),
        ("prompt", "secret prompt"),
        ("metadata", {"customer": "acme"}),
    ],
)
def test_contribution_rejects_raw_context(field, value):
    with pytest.raises(ValidationError):
        minimal_contribution(**{field: value})


def test_source_rejects_identifier():
    with pytest.raises(ValidationError):
        ContributionSource(
            source_id="source-1",
            source_token="opaque-source-token",
            source_kind="web_document",
            key_version=1,
            identifier="https://example.com/document",
        )


def test_claim_rejects_value():
    with pytest.raises(ValidationError):
        ContributionClaim(
            claim_id="claim-1",
            claim_token="opaque-claim-token",
            key_version=1,
            value="private claim",
        )
