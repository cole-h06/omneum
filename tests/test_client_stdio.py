from __future__ import annotations

import asyncio
import copy
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters

import omneum.client as client_module
from omneum.client import OmneumClientConfig, open_stdio_client
from omneum.dependency import (
    DependencyEstimatorConfig,
)
from omneum.explanations import explain_claim, explain_dependency
from omneum.information import Claim, Observation, Source, SourceReference
from omneum.oprf import VOPRFServer
from omneum.serialization import serialize_source
from stdio_state import isolated_deployment_environment


DEPLOYMENT_ID = "urn:uuid:8d96fc18-f40f-4ec7-8ae8-f3711d88b741"
PRIVATE_KEY = b"\x01" + b"\x00" * 31


def test_stdio_client(tmp_path: Path) -> None:
    async def run() -> None:
        root = Path(__file__).parents[1]
        environment, public_key, _ = isolated_deployment_environment(
            tmp_path, DEPLOYMENT_ID, PRIVATE_KEY
        )
        parameters = StdioServerParameters(
            command=str(root / ".venv/bin/python"),
            args=["-m", "omneum.server"],
            cwd=root,
            env=environment,
        )
        config = OmneumClientConfig(
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
            result = await client.evaluate_assertion(
                (
                    Observation(
                        assertion_id="assertion-a",
                        source=Source(
                            "web_publisher",
                            "https://example.com",
                        ),
                        claim=Claim(
                            "service",
                            "example",
                            "display_name",
                            "Alice",
                        ),
                        observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                        source_modified_at=None,
                        upstream_sources=(),
                        cited_sources=(),
                        parent_assertion_ids=(),
                        retrievals=(),
                    ),
                ),
                estimator=DependencyEstimatorConfig(
                    upstream_weight=0.25,
                    citation_weight=0.20,
                    assertion_lineage_weight=0.20,
                    ownership_weight=0.10,
                    temporal_weight=0.10,
                    graph_weight=0.15,
                    temporal_window_seconds=7200.0,
                ),
            )
            assert result.source_reliability[0].reliability == 1.0
            assert result.claim_support[0].support == 1.0
            assert result.pairwise_dependencies == ()

    asyncio.run(run())


def test_stdio_enterprise(tmp_path, monkeypatch):
    fixture_path = (
        Path(__file__).parent
        / "vectors"
        / "enterprise_stdio_assertion_evaluation_v1.json"
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
            assertion_id=item["assertion_id"],
            source=sources[item["source"]],
            claim=Claim(
                item["entity_namespace"],
                item["entity"],
                item["attribute"],
                item["value"],
            ),
            observed_at=datetime.fromisoformat(item["observed_at"]),
            source_modified_at=datetime.fromisoformat(item["source_modified_at"]),
            upstream_sources=tuple(
                references[name] for name in item["upstream_sources"]
            ),
            cited_sources=tuple(references[name] for name in item["cited_sources"]),
            parent_assertion_ids=tuple(item["parent_assertion_ids"]),
            retrievals=(),
        )
        for item in fixture["observations"]
    )
    estimator = DependencyEstimatorConfig(**fixture["estimator"])
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
        environment, public_key, _ = isolated_deployment_environment(
            tmp_path, DEPLOYMENT_ID, PRIVATE_KEY
        )
        parameters = StdioServerParameters(
            command=str(root / ".venv/bin/python"),
            args=["-m", "omneum.server"],
            cwd=root,
            env=environment,
        )
        config = OmneumClientConfig(
            deployment_id=DEPLOYMENT_ID,
            voprf_key_version=1,
            voprf_mode="voprf",
            voprf_ciphersuite="ristretto255-SHA512",
            linkage_encoding_version=1,
            voprf_public_key=public_key,
        )
        async with open_stdio_client(config, parameters) as client:
            first = await client.evaluate_assertion(
                observations,
                estimator=estimator,
            )
            baseline = next(
                arguments
                for name, arguments in reversed(calls)
                if name == "evaluate_assertion"
            )
            mutations = []
            unknown = copy.deepcopy(baseline)
            unknown["assertions"][0]["unknown"] = "stdio-secret-marker"
            mutations.append(unknown)
            coerced = copy.deepcopy(baseline)
            coerced["source_pairs"][0]["dependency"] = "0.5"
            mutations.append(coerced)
            oversized = copy.deepcopy(baseline)
            oversized["unknown"] = "stdio-secret-marker" * 8_192
            mutations.append(oversized)
            for mutation in mutations:
                rejected = await client._evaluator._session.call_tool(
                    "evaluate_assertion",
                    mutation,
                )
                assert rejected.isError
                assert rejected.structuredContent == {
                    "message": "Request validation failed.",
                    "omneum_code": "invalid_request",
                }
                assert "stdio-secret-marker" not in repr(rejected)
            second = await client.evaluate_assertion(
                observations,
                estimator=estimator,
            )
            claim = next(
                item
                for item in first.claim_support
                if item.claim.attribute == "return_window"
                and item.claim.value == "30 days"
            )
            pair = next(
                item
                for item in first.pairwise_dependencies
                if {
                    item.source_a.identifier,
                    item.source_b.identifier,
                } == {
                    sources["policy_manual"].identifier,
                    sources["support_portal"].identifier,
                }
            )
            claim_explanation = explain_claim(claim)
            dependency_explanation = explain_dependency(
                pair,
                source_labels={
                    sources["policy_manual"]: "Policy Manual",
                    sources["support_portal"]: "Support Portal",
                },
            )
        return first, second, claim_explanation, dependency_explanation

    first, second, claim_explanation, dependency_explanation = asyncio.run(
        run()
    )

    assert first == second
    assert claim_explanation == (
        "Return window = 30 days\n"
        "Support: 0.29\n\n"
        "Highest support\n\n"
        "Supporting sources: 3\n"
        "Independent support: 2.05\n\n"
        "Supported by 3 sources with estimated independent support of 2.05.\n"
        "Some supporting sources appear dependent.\n"
        "1 conflicting value was identified.\n\n"
        "Conflicting value:\n"
        "14 days (support 0.00)"
    )
    assert dependency_explanation == (
        "Policy Manual ↔ Support Portal\n\n"
        "Independence: 0.60\n\n"
        "• Direct citation\n"
        "• Same owner\n"
        "• Updated 1 hour apart\n"
        "• 2 matching claims"
    )
    assert first.dependency_cluster_threshold == 0.4
    assert {item.source.kind for item in first.source_reliability} == {
        "internal_resource",
        "internal_service",
        "database",
    }
    assert {item.source for item in first.source_reliability} == set(
        sources.values()
    )
    assert [
        [
            reference_names[pair.source_a],
            reference_names[pair.source_b],
            pair.dependency,
            pair.weighted_signal_coverage,
        ]
        for pair in first.pairwise_dependencies
    ] == fixture["expected"]["pairwise_dependencies"]

    claims = {
        (item.claim.attribute, item.claim.value): item
        for item in first.claim_support
    }
    majority = claims[("return_window", "30 days")]
    minority = claims[("return_window", "14 days")]
    expected_majority = fixture["expected"]["majority_claim"]
    expected_minority = fixture["expected"]["minority_claim"]
    assert majority.support == expected_majority["support"]
    assert minority.support == expected_minority["support"]
    assert majority.agreement_weight == expected_majority["agreement_weight"]
    assert minority.agreement_weight == expected_minority["agreement_weight"]
    assert majority.supporting_source_count == 3
    assert minority.supporting_source_count == 1
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
    assert {
        source_names[item.source]: [item.independence, item.contribution]
        for item in majority.supporting_sources
    } == expected_majority["supporting_sources"]
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
    assert [
        [reference_names[source] for source in cluster.sources]
        for cluster in majority.dependency_clusters
    ] == expected_majority["clusters"]
    assert [
        [reference_names[source] for source in cluster.sources]
        for cluster in minority.dependency_clusters
    ] == expected_minority["clusters"]
    assert {
        source_names[item.source]: item.reliability
        for item in first.source_reliability
    } == fixture["expected"]["source_reliability"]
    assert first.convergence.iterations == fixture["expected"]["convergence"][
        "iterations"
    ]
    assert first.convergence.convergence_tolerance == fixture["expected"][
        "convergence"
    ]["convergence_tolerance"]
    assert first.convergence.convergence_delta == fixture["expected"][
        "convergence"
    ]["convergence_delta"]

    assert counts == {
        "processes": 1,
        "initializations": 1,
        "tool_lists": 1,
    }
    assert len(sessions) == 1
    assert [name for name, _ in calls].count("evaluate_voprf") == 20
    assert [name for name, _ in calls].count("evaluate_assertion") == 5
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
    assertion_requests = [
        arguments
        for name, arguments in calls
        if name == "evaluate_assertion"
    ]
    assert assertion_requests[0] == assertion_requests[-1]
    request = assertion_requests[0]
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
        *(item["observed_at"] for item in fixture["observations"]),
        *(item["source_modified_at"] for item in fixture["observations"]),
        *(item["assertion_id"] for item in fixture["observations"]),
        *(item["entity"] for item in fixture["observations"]),
        *(item["source"] for item in fixture["observations"]),
        "commerce platform",
        "return_window",
        "support_channel",
        "Policy Manual",
        "Support Portal",
        *(
            line
            for explanation in (
                claim_explanation,
                dependency_explanation,
            )
            for line in explanation.splitlines()
            if line
        ),
    }
    assert all(value not in wire for value in private_values)

    blinded = [
        arguments["blinded_element"] for arguments in evaluation_requests
    ]
    assert blinded[:10] != blinded[10:]
    assert tuple(
        serialize_source(pair.source_a.kind, pair.source_a.identifier)
        for pair in first.pairwise_dependencies
    ) == tuple(
        sorted(
            serialize_source(pair.source_a.kind, pair.source_a.identifier)
            for pair in first.pairwise_dependencies
        )
    )
