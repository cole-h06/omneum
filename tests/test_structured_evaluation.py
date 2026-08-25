import asyncio
from datetime import datetime, timezone

from omneum import (
    AssertionSource,
    ContextMapper,
    DependencyEstimatorConfig,
    OmneumClient,
    Source,
    StructuredAssertion,
)

from test_client import make_config, make_server
from test_client_assertion_evaluation import Evaluator


def estimator():
    return DependencyEstimatorConfig(
        upstream_weight=0.25,
        citation_weight=0.20,
        assertion_lineage_weight=0.20,
        ownership_weight=0.10,
        temporal_weight=0.10,
        graph_weight=0.15,
        temporal_window_seconds=7200.0,
    )


def test_structured_evaluation(tmp_path):
    async def run():
        server = make_server(tmp_path)
        evaluator = Evaluator(server)
        client = OmneumClient(make_config(server), evaluator)

        now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)

        assertion = StructuredAssertion(
            entity_namespace="service",
            entity="mobile",
            attribute="sync",
            value={
                "effect": "full_sync_fallback",
                "threshold": 2,
                "unit": "seconds",
            },
            sources=(
                AssertionSource(
                    source=Source(
                            "internal_resource",
                            "v1:11111111-1111-1111-1111-111111111111:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                        ),
                    assertion_id="incident-report",
                    observed_at=now,
                ),
                AssertionSource(
                    source=Source(
                            "internal_resource",
                            "v1:11111111-1111-1111-1111-111111111111:bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                        ),
                    assertion_id="load-test",
                    observed_at=now,
                ),
            ),
        )

        result = await client.evaluate(
            assertion,
            estimator=estimator(),
        )

        assert len(result.claim_support) == 1

        claim = result.claim_support[0]

        assert claim.supporting_source_count == 2
        assert 1.0 < claim.estimated_independent_support_count < 2.0
        assert claim.claim.value == {
            "effect": "full_sync_fallback",
            "threshold": 2,
            "unit": "seconds",
        }

        assert len(evaluator.requests) == 1
        assert len(evaluator.requests[0].assertions) == 2

    asyncio.run(run())


def test_mapped_evaluation(tmp_path):
    async def run():
        server = make_server(tmp_path)
        evaluator = Evaluator(server)
        client = OmneumClient(make_config(server), evaluator)

        now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)

        records = (
            {
                "id": "incident-report",
                "source": (
                    "v1:11111111-1111-1111-1111-111111111111:"
                    "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
                ),
                "summary": (
                    "Sync latency past 2 seconds causes "
                    "full sync fallback."
                ),
            },
            {
                "id": "load-test",
                "source": (
                    "v1:11111111-1111-1111-1111-111111111111:"
                    "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
                ),
                "summary": (
                    "At >2s latency clients fall back "
                    "to a full sync."
                ),
            },
        )

        def normalize_sync_claim(record):
            # Application-specific semantic normalization.
            return {
                "effect": "full_sync_fallback",
                "threshold": 2,
                "unit": "seconds",
            }

        mapper = ContextMapper(
            source=lambda x: Source(
                "internal_resource",
                x["source"],
            ),
            entity_namespace=lambda x: "service",
            entity=lambda x: "mobile",
            attribute=lambda x: "sync",
            value=normalize_sync_claim,
            assertion_id="id",
            observed_at=lambda x: now,
        )

        result = await client.evaluate_mapped(
            records,
            mapper,
            estimator=estimator(),
        )

        assert len(result.claim_support) == 1

        claim = result.claim_support[0]

        assert claim.supporting_source_count == 2
        assert 1.0 < claim.estimated_independent_support_count <= 2.0
        assert claim.claim.value == {
            "effect": "full_sync_fallback",
            "threshold": 2,
            "unit": "seconds",
        }

        assert len(evaluator.requests) == 1
        assert len(evaluator.requests[0].assertions) == 2

    asyncio.run(run())
