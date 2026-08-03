from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters

import verity.client as client_module
from verity.base64url import encode_unpadded
from verity.client import VerityClientConfig, open_stdio_client
from verity.dependency import (
    DependencyEstimatorConfig,
    estimate_dependencies,
)
from verity.information import Claim, Observation, Source, SourceReference
from verity.oprf import VOPRFServer
from verity.serialization import serialize_source


DEPLOYMENT_ID = "urn:uuid:8d96fc18-f40f-4ec7-8ae8-f3711d88b741"
PRIVATE_KEY = b"\x01" + b"\x00" * 31


def test_stdio_client(tmp_path: Path) -> None:
    async def run() -> None:
        root = Path(__file__).parents[1]
        private_key_file = tmp_path / "voprf.key"
        private_key_file.write_bytes(PRIVATE_KEY)
        public_key = VOPRFServer(private_key_file).public_key
        environment = {
            **os.environ,
            "PYTHONPATH": str(root),
            "VERITY_DEPLOYMENT_ID": DEPLOYMENT_ID,
            "VERITY_VOPRF_KEY_VERSION": "1",
            "VERITY_VOPRF_PUBLIC_KEY": encode_unpadded(
                public_key, expected_length=32
            ),
            "VERITY_VOPRF_PRIVATE_KEY_FILE": str(private_key_file),
        }
        parameters = StdioServerParameters(
            command=str(root / ".venv/bin/python"),
            args=["-m", "verity.server"],
            cwd=root,
            env=environment,
        )
        config = VerityClientConfig(
            deployment_id=DEPLOYMENT_ID,
            voprf_key_version=1,
            voprf_mode="voprf",
            voprf_ciphersuite="ristretto255-SHA512",
            linkage_encoding_version=1,
            voprf_public_key=public_key,
        )
        async with open_stdio_client(config, parameters) as client:
            first = await client.link_claim(
                "service",
                " Example ",
                " Display Name ",
                " Alice ",
            )
            second = await client.link_claim(
                "service",
                "example",
                "display_name",
                "Alice",
            )
            assert len(first.value) == 64
            assert first.value == second.value
            result = await client.infer_credibility(
                (
                    Observation(
                        "assertion-a",
                        Source(
                            "web_publisher",
                            "https://example.com",
                        ),
                        Claim(
                            "service",
                            "example",
                            "display_name",
                            "Alice",
                        ),
                        datetime(2026, 1, 1, tzinfo=timezone.utc),
                        (),
                        (),
                        (),
                    ),
                ),
                estimator=DependencyEstimatorConfig(
                    0.25,
                    0.3,
                    0.15,
                    0.15,
                    0.15,
                    7200.0,
                ),
            )
            assert result.source_credibility[0].credibility == 1.0
            assert result.claim_support[0].support == 1.0
            assert result.pairwise_dependencies == ()

    asyncio.run(run())


def test_stdio_enterprise(tmp_path, monkeypatch):
    fixture_path = (
        Path(__file__).parent
        / "vectors"
        / "enterprise_stdio_inference_v1.json"
    )
    fixture = json.loads(fixture_path.read_text())
    sources = {
        item["name"]: Source(
            item["kind"],
            item["identifier"],
            item["owner_id"],
        )
        for item in fixture["sources"]
    }
    references = {
        name: SourceReference(source.kind, source.identifier)
        for name, source in sources.items()
    }
    observations = tuple(
        Observation(
            item["assertion_id"],
            sources[item["source"]],
            Claim(
                item["entity_namespace"],
                item["entity"],
                item["attribute"],
                item["value"],
            ),
            datetime.fromisoformat(item["source_timestamp"]),
            tuple(item["provenance_ids"]),
            tuple(references[name] for name in item["cited_sources"]),
            tuple(item["parent_assertion_ids"]),
        )
        for item in fixture["observations"]
    )
    estimator = DependencyEstimatorConfig(**fixture["estimator"])
    expected_pairs, expected_clusters = estimate_dependencies(
        tuple(sources.values()),
        observations,
        estimator,
    )
    source_names = {source: name for name, source in sources.items()}
    reference_names = {
        reference: name for name, reference in references.items()
    }

    calls = []
    sessions = set()
    counts = {"processes": 0, "initializations": 0, "tool_lists": 0}
    original_stdio = client_module.stdio_client
    original_initialize = ClientSession.initialize
    original_list_tools = ClientSession.list_tools
    original_call_tool = ClientSession.call_tool

    @asynccontextmanager
    async def tracked_stdio(*args, **kwargs):
        counts["processes"] += 1
        async with original_stdio(*args, **kwargs) as streams:
            yield streams

    async def tracked_initialize(self):
        sessions.add(id(self))
        counts["initializations"] += 1
        return await original_initialize(self)

    async def tracked_list_tools(self, *args, **kwargs):
        sessions.add(id(self))
        counts["tool_lists"] += 1
        return await original_list_tools(self, *args, **kwargs)

    async def tracked_call_tool(self, name, arguments=None, *args, **kwargs):
        sessions.add(id(self))
        calls.append((name, json.loads(json.dumps(arguments))))
        return await original_call_tool(
            self,
            name,
            arguments,
            *args,
            **kwargs,
        )

    monkeypatch.setattr(client_module, "stdio_client", tracked_stdio)
    monkeypatch.setattr(ClientSession, "initialize", tracked_initialize)
    monkeypatch.setattr(ClientSession, "list_tools", tracked_list_tools)
    monkeypatch.setattr(ClientSession, "call_tool", tracked_call_tool)

    async def run():
        root = Path(__file__).parents[1]
        private_key_file = tmp_path / "enterprise-voprf.key"
        private_key_file.write_bytes(PRIVATE_KEY)
        public_key = VOPRFServer(private_key_file).public_key
        environment = {
            **os.environ,
            "PYTHONPATH": str(root),
            "VERITY_DEPLOYMENT_ID": DEPLOYMENT_ID,
            "VERITY_VOPRF_KEY_VERSION": "1",
            "VERITY_VOPRF_PUBLIC_KEY": encode_unpadded(
                public_key,
                expected_length=32,
            ),
            "VERITY_VOPRF_PRIVATE_KEY_FILE": str(private_key_file),
        }
        parameters = StdioServerParameters(
            command=str(root / ".venv/bin/python"),
            args=["-m", "verity.server"],
            cwd=root,
            env=environment,
        )
        config = VerityClientConfig(
            deployment_id=DEPLOYMENT_ID,
            voprf_key_version=1,
            voprf_mode="voprf",
            voprf_ciphersuite="ristretto255-SHA512",
            linkage_encoding_version=1,
            voprf_public_key=public_key,
        )
        async with open_stdio_client(config, parameters) as client:
            first = await client.infer_credibility(
                observations,
                estimator=estimator,
            )
            second = await client.infer_credibility(
                observations,
                estimator=estimator,
            )
        return first, second

    first, second = asyncio.run(run())

    assert first == second
    assert first.pairwise_dependencies == expected_pairs
    assert first.dependency_cluster_threshold == 0.4
    assert {item.source.kind for item in first.source_credibility} == {
        "internal_resource",
        "internal_service",
        "database",
    }
    assert {item.source for item in first.source_credibility} == set(
        sources.values()
    )
    expected_order = tuple(
        (pair.source_a, pair.source_b)
        for pair in expected_pairs
    )
    assert tuple(
        (pair.source_a, pair.source_b)
        for pair in first.pairwise_dependencies
    ) == expected_order
    assert len(expected_pairs) == 6
    assert [
        [
            reference_names[pair.source_a],
            reference_names[pair.source_b],
            pair.dependency,
            pair.weighted_signal_coverage,
        ]
        for pair in expected_pairs
    ] == fixture["expected"]["pairwise_dependencies"]
    assert all(pair.weighted_signal_coverage == 1.0 for pair in expected_pairs)
    assert any(pair.dependency == 0.0 for pair in expected_pairs)
    assert any(0.0 < pair.dependency < 1.0 for pair in expected_pairs)

    claims = {
        (item.claim.attribute, item.claim.value): item
        for item in first.claim_support
    }
    majority = claims[("return_window", "30 days")]
    minority = claims[("return_window", "14 days")]
    expected_majority = fixture["expected"]["majority_claim"]
    expected_minority = fixture["expected"]["minority_claim"]
    assert majority.agreement_weight == 0.75
    assert minority.agreement_weight == 0.25
    assert majority.support == expected_majority["support"]
    assert minority.support == expected_minority["support"]
    assert majority.agreement_weight == expected_majority["agreement_weight"]
    assert minority.agreement_weight == expected_minority["agreement_weight"]
    assert majority.supporting_source_count == 3
    assert minority.supporting_source_count == 1
    assert majority.dependency_confidence == 1.0
    assert (
        majority.estimated_independent_support_count
        == expected_majority["estimated_independent_support_count"]
    )
    assert (
        minority.estimated_independent_support_count
        == expected_minority["estimated_independent_support_count"]
    )
    assert (
        majority.dependency_confidence
        == expected_majority["dependency_confidence"]
    )
    assert (
        minority.dependency_confidence
        == expected_minority["dependency_confidence"]
    )
    assert 1.0 < majority.estimated_independent_support_count < 3.0
    assert {
        source_names[item.source]: [item.independence, item.contribution]
        for item in majority.supporting_sources
    } == expected_majority["supporting_sources"]
    assert all(
        0.0 < item.independence < 1.0
        for item in majority.supporting_sources
    )
    assert sum(
        item.contribution for item in majority.supporting_sources
    ) == pytest.approx(majority.support, rel=0.0, abs=1e-15)
    assert majority.conflicting_claims == (
        client_module.ConflictingClaimResult(minority.claim, minority.support),
    )
    assert minority.conflicting_claims == (
        client_module.ConflictingClaimResult(majority.claim, majority.support),
    )
    assert majority.is_attribute_max_support
    assert not minority.is_attribute_max_support
    assert claims[("support_channel", "email")].support == majority.support
    assert claims[("support_channel", "chat")].support == minority.support
    assert all(item.conflicting_claims for item in first.claim_support)
    assert len(majority.dependency_clusters) == 1
    assert [
        reference_names[source]
        for source in majority.dependency_clusters[0].sources
    ] == expected_majority["cluster"]
    assert majority.dependency_clusters[0].sources == tuple(
        source
        for cluster in expected_clusters
        for source in cluster.sources
        if source.kind != "internal_service"
    )
    assert minority.dependency_clusters[0].sources == (
        references["orders_api"],
    )
    assert [
        reference_names[source]
        for source in minority.dependency_clusters[0].sources
    ] == expected_minority["cluster"]
    assert {
        source_names[item.source]: item.credibility
        for item in first.source_credibility
    } == fixture["expected"]["source_credibility"]
    assert first.convergence.iterations == fixture["expected"]["convergence"][
        "iterations"
    ]
    assert (
        first.convergence.convergence_tolerance
        == fixture["expected"]["convergence"]["convergence_tolerance"]
    )
    assert (
        first.convergence.maximum_credibility_delta
        == fixture["expected"]["convergence"]["maximum_credibility_delta"]
    )

    assert counts == {
        "processes": 1,
        "initializations": 1,
        "tool_lists": 1,
    }
    assert len(sessions) == 1
    assert [name for name, _ in calls].count("evaluate_voprf") == 20
    assert [name for name, _ in calls].count("infer_credibility") == 2
    evaluation_requests = [
        arguments
        for name, arguments in calls
        if name == "evaluate_voprf"
    ]
    assert all(
        set(request) == {
            "protocol_version",
            "deployment_id",
            "voprf_key_version",
            "voprf_mode",
            "voprf_ciphersuite",
            "linkage_encoding_version",
            "blinded_element",
        }
        for request in evaluation_requests
    )
    inference_requests = [
        arguments
        for name, arguments in calls
        if name == "infer_credibility"
    ]
    assert inference_requests[0] == inference_requests[1]
    request = inference_requests[0]
    assert set(request) == {
        "protocol_version",
        "deployment_id",
        "voprf_key_version",
        "voprf_mode",
        "voprf_ciphersuite",
        "linkage_encoding_version",
        "assertions",
        "source_pairs",
    }
    assert len(request["assertions"]) == 8
    assert len(request["source_pairs"]) == 6
    source_tokens = {item["source_id"] for item in request["assertions"]}
    attribute_tokens = {
        item["attribute_id"] for item in request["assertions"]
    }
    claim_tokens = {item["claim_id"] for item in request["assertions"]}
    assert len(source_tokens) == 4
    assert len(attribute_tokens) == 2
    assert len(claim_tokens) == 4
    assert source_tokens.isdisjoint(attribute_tokens)
    assert source_tokens.isdisjoint(claim_tokens)
    assert attribute_tokens.isdisjoint(claim_tokens)
    assert all(
        len(token) == 86
        for token in source_tokens | attribute_tokens | claim_tokens
    )
    assert request["source_pairs"] == sorted(
        request["source_pairs"],
        key=lambda pair: (pair["source_a_id"], pair["source_b_id"]),
    )
    assert all(
        pair["source_a_id"] < pair["source_b_id"]
        for pair in request["source_pairs"]
    )

    wire = json.dumps(calls, sort_keys=True)
    private_values = {
        fixture["scope_uuid"],
        *(source.identifier for source in sources.values()),
        *(source.owner_id for source in sources.values()),
        *(item["attribute"] for item in fixture["observations"]),
        *(item["value"] for item in fixture["observations"]),
        *(item["source_timestamp"] for item in fixture["observations"]),
        *(item["assertion_id"] for item in fixture["observations"]),
        *(item["entity"] for item in fixture["observations"]),
        *(item["source"] for item in fixture["observations"]),
        "commerce platform",
        "return_window",
        "support_channel",
        *(
            provenance
            for item in fixture["observations"]
            for provenance in item["provenance_ids"]
        ),
    }
    assert all(value not in wire for value in private_values)

    blinded = [
        arguments["blinded_element"] for arguments in evaluation_requests
    ]
    assert blinded[:10] != blinded[10:]
    assert tuple(
        serialize_source(pair.source_a.kind, pair.source_a.identifier)
        for pair in expected_pairs
    ) == tuple(
        sorted(
            serialize_source(pair.source_a.kind, pair.source_a.identifier)
            for pair in expected_pairs
        )
    )
