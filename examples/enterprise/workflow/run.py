from __future__ import annotations

import argparse
import asyncio
from typing import TYPE_CHECKING

from omneum import ContextEvaluation, DependencyEstimatorConfig, Observation, OmneumClientConfig
from omneum.mcp import StdioServerParameters

if TYPE_CHECKING:
    from examples.context_preparation import GenerationInput, PreparationOptions

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
from .retrieval import collect_chunks


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
TOKEN_BUDGET = 600


def collect_observations() -> tuple[Observation, ...]:
    return tuple(
        observation
        for agent in RETRIEVAL_AGENTS
        for observation in agent()
    )


def estimator_config() -> DependencyEstimatorConfig:
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


async def run_workflow(
    config: OmneumClientConfig | None = None,
    server: StdioServerParameters | None = None,
    *, token_budget: int = TOKEN_BUDGET,
    preparation: PreparationOptions | None = None,
) -> tuple[ContextEvaluation, str]:
    result = await prepare_workflow(config, server, token_budget=token_budget, preparation=preparation)
    return result["evaluation"], result["messages"][1]["content"]


async def prepare_workflow(
    config: OmneumClientConfig | None = None,
    server: StdioServerParameters | None = None,
    *, token_budget: int = TOKEN_BUDGET,
    preparation: PreparationOptions | None = None,
) -> GenerationInput:
    # Framework examples import the enterprise question and estimator during initialization.
    from examples.context_preparation import prepare_generation

    observations = collect_observations()
    return await prepare_generation(
        observations, chunks=collect_chunks(observations), question=QUESTION,
        estimator=estimator_config(), token_budget=token_budget, preparation=preparation,
        config=config, server=server,
    )


async def execute(
    options: PreparationOptions, args: argparse.Namespace, scenario: str | None,
) -> tuple[GenerationInput, None]:
    return await prepare_workflow(preparation=options), None


def main() -> None:
    from examples.context_output import run_cli

    asyncio.run(run_cli("enterprise", execute, debug_json=DEBUG_JSON))


DEBUG_JSON = False

if __name__ == "__main__":
    main()
