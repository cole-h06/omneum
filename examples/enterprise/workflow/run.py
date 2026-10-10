from omneum.explanations import explain_evaluation
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
        estimator_version="dependency-estimator-v4",
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
        result = await client.evaluate_context(
            collect_observations(),
            estimator=estimator_config(),
        )
    return result, render_result(result)


def render_result(result):
    sections = [QUESTION, render_conclusion(result), "Source reliability"]
    for item in sorted(
        result.source_reliability,
        key=lambda value: SOURCE_LABELS.get(
            value.source, value.source.identifier
        ),
    ):
        sections.append(
            f"{SOURCE_LABELS.get(item.source, item.source.identifier)}\n"
            f"Reliability: {item.reliability:.2f}"
        )

    sections.append(explain_evaluation(result))

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
                explain_dependency(
                    item,
                    source_labels={
                        **SOURCE_LABELS,
                        **{
                            source.source: source.source.identifier
                            for source in result.source_reliability
                            if source.source not in SOURCE_LABELS
                        },
                    },
                )
            )
    return "\n\n".join(sections)


def render_conclusion(result):
    """Apply an example application policy to Omneum's claim-support results."""
    required = (
        "input_data_policy",
        "provider_retention",
        "processing_region",
    )

    groups = {}
    for item in result.claim_support:
        groups.setdefault(item.claim.attribute, []).append(item)

    selected = {}
    for attribute in required:
        candidates = sorted(
            groups.get(attribute, ()),
            key=lambda item: item.support,
            reverse=True,
        )

        if not candidates:
            return (
                "Application decision: ESCALATE\n"
                f"Missing evidence for {attribute}."
            )

        if (
            len(candidates) > 1
            and candidates[0].support <= candidates[1].support
        ):
            return (
                "Application decision: RETRIEVE MORE\n"
                f"Unresolved competing claims for {attribute}."
            )

        selected[attribute] = candidates[0]

    lines = [
        "Application decision: EVALUATION COMPLETE",
        "Highest-supported claims:",
    ]

    for attribute in required:
        item = selected[attribute]
        lines.append(
            f"{attribute}: {item.claim.value} "
            f"(support {item.support:.4f}, "
            f"independent support "
            f"{item.estimated_independent_support_count:.2f})"
        )

    lines.append(
        "These are relative evidence-support scores, "
        "not probabilities or authorization decisions."
    )

    return "\n".join(lines)


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
