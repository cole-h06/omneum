import asyncio
import json

import pytest
from mcp import ClientSession

from examples.enterprise.agents.api import api_agent
from examples.enterprise.agents.common import (
    BRIEF_SOURCE,
    GATEWAY_SOURCE,
    POLICY_SOURCE,
    REGISTRY_SOURCE,
    RUNBOOK_SOURCE,
    VENDOR_SOURCE,
)
from examples.enterprise.agents.documents import documents_agent
from examples.enterprise.agents.research import research_agent
from examples.enterprise.agents.search import search_agent
from examples.enterprise.agents.sql import sql_agent
from examples.enterprise.config import example_deployment
from examples.enterprise.workflow.run import (
    RETRIEVAL_AGENTS,
    SOURCE_LABELS,
    collect_observations,
    estimator_config,
    run_workflow,
)
from omneum.dependency import estimate_dependencies
SOURCES = {
    "policy": POLICY_SOURCE,
    "runbook": RUNBOOK_SOURCE,
    "brief": BRIEF_SOURCE,
    "registry": REGISTRY_SOURCE,
    "gateway": GATEWAY_SOURCE,
    "vendor": VENDOR_SOURCE,
}


def test_observations():
    values = collect_observations()

    assert RETRIEVAL_AGENTS == (
        documents_agent,
        research_agent,
        sql_agent,
        api_agent,
        search_agent,
    )
    assert tuple(len(agent()) for agent in RETRIEVAL_AGENTS) == (6, 3, 3, 3, 2)
    assert len(values) == 17
    assert len({value.source for value in values}) == 6
    assert {value.claim.attribute for value in values} == {
        "Input Data Policy",
        "Provider Retention",
        "Processing Region",
    }
    assert {value.claim.value for value in values} == {
        "redacted customer content only",
        "unredacted customer content allowed",
        "0 days",
        "30 days",
        "EU",
        "US",
    }
    assert all(value.observed_at is not None for value in values)
    assert all(value.source_modified_at is not None for value in values)
    assert all(value.upstream_sources is not None for value in values)
    assert all(value.cited_sources is not None for value in values)
    assert all(value.parent_assertion_ids is not None for value in values)

    by_id = {value.assertion_id: value for value in values}
    for suffix in ("input-data", "retention", "region"):
        brief = by_id[f"brief-{suffix}"]
        registry = by_id[f"registry-{suffix}"]
        gateway = by_id[f"gateway-{suffix}"]
        assert brief.parent_assertion_ids == (f"runbook-{suffix}",)
        assert registry.parent_assertion_ids == (f"policy-{suffix}",)
        assert gateway.parent_assertion_ids == (f"registry-{suffix}",)


def test_dependencies():
    values = collect_observations()
    pairs, clusters = estimate_dependencies(
        tuple(SOURCES.values()),
        values,
        estimator_config(),
    )
    names = {
        (source.kind, source.identifier): name
        for name, source in SOURCES.items()
    }
    dependencies = {
        frozenset((
            names[(pair.source_a.kind, pair.source_a.identifier)],
            names[(pair.source_b.kind, pair.source_b.identifier)],
        )): pair.dependency
        for pair in pairs
    }

    assert len(pairs) == 15
    assert dependencies[frozenset(("runbook", "brief"))] == pytest.approx(
        0.5750000000000001
    )
    assert dependencies[frozenset(("policy", "registry"))] == pytest.approx(
        0.5416666666666667
    )
    assert dependencies[frozenset(("registry", "gateway"))] == pytest.approx(
        0.5416666666666667
    )
    assert dependencies[frozenset(("vendor", "gateway"))] == pytest.approx(
        0.0375
    )
    assert {
        frozenset(
            names[(source.kind, source.identifier)]
            for source in cluster.sources
        )
        for cluster in clusters
    } == {
        frozenset(("policy", "registry", "gateway")),
        frozenset(("runbook", "brief")),
        frozenset(("vendor",)),
    }


def test_stdio_workflow(monkeypatch):
    calls = []
    original_call_tool = ClientSession.call_tool

    async def tracked_call_tool(self, name, arguments=None, *args, **kwargs):
        calls.append((id(self), name, json.loads(json.dumps(arguments))))
        return await original_call_tool(
            self,
            name,
            arguments,
            *args,
            **kwargs,
        )

    monkeypatch.setattr(ClientSession, "call_tool", tracked_call_tool)

    async def run():
        with example_deployment() as (config, server):
            first = await run_workflow(config, server)
        second = await run_workflow()
        return first, second

    (first, first_output), (second, second_output) = asyncio.run(run())

    assert first == second
    assert first_output == second_output
    assert len(first.source_reliability) == 6
    assert len(first.claim_support) == 6
    assert len(first.pairwise_dependencies) == 15
    assert "Customer content must be redacted." in first_output
    assert "Provider retention must be 0 days." in first_output
    assert "Processing must remain in the EU." in first_output
    assert "Independent support: 2.40" in first_output
    assert "Stale deployment runbook ↔ Copilot readiness brief" in first_output
    assert "corroboration" not in first_output.lower()

    sessions = {session for session, _, _ in calls}
    assert len(sessions) == 2
    for session in sessions:
        session_calls = [item for item in calls if item[0] == session]
        assert sum(name == "evaluate_voprf" for _, name, _ in session_calls) == 15
        assert sum(name == "evaluate_assertion" for _, name, _ in session_calls) == 1

    assertion_requests = [
        arguments
        for _, name, arguments in calls
        if name == "evaluate_assertion"
    ]
    observations = collect_observations()
    private_values = {
        value.assertion_id
        for value in observations
    } | {
        value.source.identifier
        for value in observations
    } | {
        value.source.owner_id
        for value in observations
    } | {
        value.source_modified_at.isoformat()
        for value in observations
    } | {
        value.claim.entity
        for value in observations
    } | {
        value.claim.attribute
        for value in observations
    } | {
        value.claim.value
        for value in observations
    } | set(SOURCE_LABELS.values())
    for request in assertion_requests:
        encoded = json.dumps(request)
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
        assert len(request["assertions"]) == 17
        assert len(request["source_pairs"]) == 15
        stack = [request]
        wire_strings = set()
        while stack:
            value = stack.pop()
            if type(value) is dict:
                stack.extend(value.values())
            elif type(value) is list:
                stack.extend(value)
            elif type(value) is str:
                wire_strings.add(value)
        assert private_values.isdisjoint(wire_strings)
        assert "Application conclusion" not in encoded
