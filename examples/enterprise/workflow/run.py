import asyncio

from omneum import (
    DependencyEstimatorConfig,
    explain_claim,
    explain_dependency,
    open_stdio_client,
)

from ..agents.api import api_agent
from ..agents.common import (
    BRIEF_SOURCE,
    GATEWAY_SOURCE,
    POLICY_SOURCE,
    REGISTRY_SOURCE,
    RUNBOOK_SOURCE,
    VENDOR_SOURCE,
)
from ..agents.documents import documents_agent
from ..agents.research import research_agent
from ..agents.search import search_agent
from ..agents.sql import sql_agent
from ..config import example_deployment


QUESTION = (
    "May the EU Customer Support Copilot send unredacted customer-ticket "
    "content to the approved hosted model in production? What "
    "provider-retention and processing-region settings are required?"
)
RETRIEVAL_AGENTS = (
    documents_agent,
    research_agent,
    sql_agent,
    api_agent,
    search_agent,
)
SOURCE_LABELS = {
    POLICY_SOURCE: "AI data-governance policy",
    RUNBOOK_SOURCE: "Stale deployment runbook",
    BRIEF_SOURCE: "Copilot readiness brief",
    REGISTRY_SOURCE: "Model registry",
    GATEWAY_SOURCE: "AI gateway",
    VENDOR_SOURCE: "Vendor enterprise data controls",
}


def collect_observations():
    return tuple(
        observation
        for agent in RETRIEVAL_AGENTS
        for observation in agent()
    )


def estimator_config():
    return DependencyEstimatorConfig(
        upstream_weight=25.0,
        citation_weight=20.0,
        assertion_lineage_weight=20.0,
        ownership_weight=10.0,
        temporal_weight=10.0,
        graph_weight=15.0,
        temporal_window_seconds=172_800.0,
        estimator_version="dependency-estimator-v1",
        dependency_cluster_threshold=0.4,
    )


async def run_workflow(config=None, server=None):
    if config is None and server is None:
        with example_deployment() as deployment:
            return await run_workflow(*deployment)
    if config is None or server is None:
        raise TypeError("config and server must be supplied together")
    async with open_stdio_client(
        config,
        server,
    ) as client:
        result = await client.evaluate_assertion(
            collect_observations(),
            estimator=estimator_config(),
        )
    return result, render_result(result)


def render_result(result):
    sections = [QUESTION, render_conclusion(result), "Source reliability"]
    for item in sorted(
        result.source_reliability,
        key=lambda value: SOURCE_LABELS[value.source],
    ):
        sections.append(
            f"{SOURCE_LABELS[item.source]}\n"
            f"Reliability: {item.reliability:.2f}"
        )

    sections.append("Claims")
    for item in sorted(
        result.claim_support,
        key=lambda value: (
            value.claim.attribute,
            str(value.claim.value),
        ),
    ):
        sections.append(
            explain_claim(item, source_labels=SOURCE_LABELS)
        )

    sections.append("Pair dependencies")
    for item in result.pairwise_dependencies:
        if any(
            getattr(item.signals, f"{name}_observable")
            and getattr(item.signals, name) > 0.0
            for name in (
                "upstream",
                "citation",
                "assertion_lineage",
                "ownership",
                "temporal",
                "graph",
            )
        ):
            sections.append(
                explain_dependency(item, source_labels=SOURCE_LABELS)
            )
    return "\n\n".join(sections)


def render_conclusion(result):
    winners = {}
    for item in result.claim_support:
        if item.is_attribute_max_support:
            winners.setdefault(item.claim.attribute, []).append(item)
    expected = {
        "input_data_policy": "redacted customer content only",
        "provider_retention": "0 days",
        "processing_region": "EU",
    }
    for attribute, value in expected.items():
        if (
            len(winners.get(attribute, ())) != 1
            or winners[attribute][0].claim.value != value
        ):
            raise RuntimeError("The expected deployment controls were not resolved.")

    runbook_brief = _dependency(result, RUNBOOK_SOURCE, BRIEF_SOURCE)
    if not (
        runbook_brief.signals.assertion_lineage > 0.0
        and runbook_brief.signals.ownership > 0.0
    ):
        raise RuntimeError("Readiness-brief lineage was not preserved.")

    vendor_claims = {
        item.claim.attribute
        for item in result.claim_support
        if any(
            source.source == VENDOR_SOURCE
            for source in item.supporting_sources
        )
    }
    if vendor_claims != {"provider_retention", "processing_region"}:
        raise RuntimeError("Vendor support was not preserved.")

    return "\n".join((
        "Application conclusion",
        "Customer content must be redacted.",
        "Provider retention must be 0 days.",
        "Processing must remain in the EU.",
        "The stale deployment runbook and recent readiness brief disagree "
        "with these controls.",
        "The readiness brief is derived from the stale runbook and is not "
        "an independent source.",
        "Vendor documentation confirms only:",
        "• Provider retention",
        "• Processing region",
    ))


def _dependency(result, first, second):
    identities = {
        (first.kind, first.identifier),
        (second.kind, second.identifier),
    }
    return next(
        item
        for item in result.pairwise_dependencies
        if {
            (item.source_a.kind, item.source_a.identifier),
            (item.source_b.kind, item.source_b.identifier),
        } == identities
    )


def main():
    _, output = asyncio.run(run_workflow())
    print(output)


if __name__ == "__main__":
    main()
