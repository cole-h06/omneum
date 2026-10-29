import asyncio
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from omneum.sources import internal_source_id
from omneum import (
    Claim,
    Observation,
    ContextMapper,
    DependencyEstimatorConfig,
    OmneumClient,
    Source,
)

from test_client import make_config, make_server
from test_client_evaluation import Evaluator


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


@pytest.fixture
def client(tmp_path):
    server = make_server(tmp_path)
    evaluator = Evaluator(server)
    return OmneumClient(make_config(server), evaluator), evaluator


def test_shared_claim(client):
    async def run():
        sdk, evaluator = client

        now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)

        claim = Claim(
            entity_namespace="service",
            entity="mobile",
            attribute="sync",
            value={
                "effect": "full_sync_fallback",
                "threshold": 2,
                "unit": "seconds",
            },
        )
        observations = tuple(
            Observation(
                observation_id=identifier,
                source=Source("internal_resource", source_id),
                claim=claim,
                observed_at=now,
            )
            for identifier, source_id in (
                ("incident-report", "v1:11111111-1111-1111-1111-111111111111:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
                ("load-test", "v1:11111111-1111-1111-1111-111111111111:bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
            )
        )
        result = await sdk._evaluate_context(
            observations,
            estimator=estimator(),
        )

        assert len(result.claim_support) == 1

        claim = result.claim_support[0]

        assert claim.supporting_source_count == 2
        assert claim.estimated_independent_support_count == 2.0
        assert claim.claim.value == {
            "effect": "full_sync_fallback",
            "threshold": 2,
            "unit": "seconds",
        }

        assert len(evaluator.requests) == 1
        assert len(evaluator.requests[0].assertions) == 2

    asyncio.run(run())


def test_mapped_evaluation(client):
    async def run():
        sdk, evaluator = client

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

        def sync_claim(record):
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
            value=sync_claim,
            observation_id="id",
            observed_at=lambda x: now,
        )

        result = await sdk._evaluate_mapped(
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


@pytest.mark.parametrize("mode", ["omitted", "none", "default", "custom"])
def test_mapped_estimator(client, mode):
    async def run():
        sdk, evaluator = client
        now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
        records = (
            {"id": "a", "url": "https://a.example", "upstream": ["https://origin.example"]},
            {"id": "b", "url": "https://b.example", "upstream": ["https://origin.example"]},
            {"id": "c", "url": "https://c.example", "upstream": []},
        )
        mapper = ContextMapper(
            source=lambda x: Source("web_document", x["url"]),
            entity_namespace=lambda x: "service",
            entity=lambda x: "mobile",
            attribute=lambda x: "sync",
            value=lambda x: "full_sync_fallback",
            observation_id="id",
            observed_at=lambda x: now,
            upstream_sources=lambda x: [
                {"kind": "web_document", "identifier": url}
                for url in x["upstream"]
            ],
            cited_sources=lambda x: [],
        )
        config = DependencyEstimatorConfig(
            upstream_weight=1.0,
            citation_weight=0.0,
            assertion_lineage_weight=0.0,
            ownership_weight=0.0,
            temporal_weight=0.0,
            graph_weight=0.0,
            temporal_window_seconds=7200.0,
        )
        if mode == "custom":
            config = replace(
                config,
                upstream_weight=0.0,
                citation_weight=1.0,
                dependency_cluster_threshold=0.5,
            )

        if mode == "omitted":
            result = await sdk._evaluate_mapped(records, mapper)
        else:
            result = await sdk._evaluate_mapped(
                records,
                mapper,
                estimator=None if mode == "none" else config,
            )
        expected = await sdk._evaluate_context(
            mapper.map_many(records),
            estimator=config,
        )

        assert result == expected
        assert result.estimated_independent_support == (
            3.0 if mode == "custom" else 2.0
        )
        assert sorted(pair.dependency for pair in result.pairwise_dependencies) == (
            [0.0, 0.0, 0.0] if mode == "custom" else [0.0, 0.0, 1.0]
        )
        assert result.dependency_cluster_threshold == config.dependency_cluster_threshold
        assert len(evaluator.requests) == 2

    asyncio.run(run())


def test_mapped_tool_results(client):
    async def run():
        sdk, evaluator = client

        now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)

        records = (
            {
                "tool_call_id": "call-8472",
                "tool_name": "get_service_config",
                "output": {
                    "service_id": "payments-api",
                    "retention": {"value": 90, "unit": "days"},
                },
                "resource": {
                    "id": "config-1847",
                    "kind": "database_record",
                },
                "timestamp": now,
            },
            {
                "tool_call_id": "call-9134",
                "tool_name": "get_service_config",
                "output": {
                    "service_id": "payments-api",
                    "retention": {"value": 90, "unit": "days"},
                },
                "resource": {
                    "id": "config-2911",
                    "kind": "database_record",
                },
                "timestamp": now,
            },
        )

        mapper = ContextMapper(
            source=lambda x: Source(
                kind="internal_resource",
                identifier=internal_source_id(
                        "12345678-1234-4abc-8def-123456789abc",
                        x["resource"]["id"],
                    ),
            ),
            entity_namespace=lambda x: "service",
            entity="output.service_id",
            attribute=lambda x: "retention",
            value="output.retention",
            observation_id="tool_call_id",
            observed_at="timestamp",
            metadata={"tool_name": "tool_name"},
        )

        result = await sdk._evaluate_mapped(
            records,
            mapper,
            estimator=estimator(),
        )

        assert len(result.claim_support) == 1

        claim = result.claim_support[0]

        assert claim.supporting_source_count == 2
        assert claim.claim.entity == "payments-api"
        assert claim.claim.attribute == "retention"
        assert claim.claim.value == {"value": 90, "unit": "days"}

        assert len(evaluator.requests) == 1
        assert len(evaluator.requests[0].assertions) == 2

    asyncio.run(run())
