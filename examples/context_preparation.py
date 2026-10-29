import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any, TypedDict

from omneum import ContextEvaluation, DependencyEstimatorConfig, Observation, OmneumClientConfig, Source, open_stdio_client, reconstruct_context
from omneum.context_selection import claim_id
from omneum.mcp import StdioServerParameters

from examples.enterprise.config import example_deployment
from examples.enterprise.workflow.generate import ModelMessage, generation_messages
from examples.enterprise.workflow.retrieval import (
    DATA, SOURCE_FILES, RetrievedChunk, validate_chunks,
)
from examples.langgraph.routing.retrieval import STRATEGIES, retrieval_record


@dataclass(frozen=True, slots=True)
class PreparationOptions:
    token_budget: int = 600
    compare: bool = False
    include_telemetry: bool = False
    collect_telemetry: bool = False

    def __post_init__(self) -> None:
        if type(self.token_budget) is not int or self.token_budget < 0:
            raise ValueError("token_budget must be a nonnegative integer")
        for name in ("compare", "include_telemetry", "collect_telemetry"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be a bool")


class GenerationInput(TypedDict):
    retrieved_chunks: list[RetrievedChunk]
    prepared_context: dict[str, Any]
    messages: list[ModelMessage]
    query_diagnostics: dict[str, Any]
    evaluation: ContextEvaluation
    question: str
    configuration: dict[str, Any]
    structural_evaluation: list[dict[str, Any]]
    comparison: dict[str, Any] | None


def collect_chunks(observations: Sequence[Observation]) -> list[RetrievedChunk]:
    originals = {
        source: (DATA / filename).stem
        for source, filename in SOURCE_FILES
    }
    texts = {
        source: (DATA / filename).read_text(encoding="utf-8")
        for source, filename in SOURCE_FILES
    }
    for strategy in STRATEGIES:
        for attempt in (1, 2):
            record = retrieval_record(strategy, attempt)
            source = Source(**record["source"])
            originals[source] = record["record_id"]
            texts[source] = json.dumps(record, indent=2, allow_nan=False)
    groups: dict[Source, list[Observation]] = {}
    for observation in observations:
        if observation.source not in originals:
            raise ValueError("retrieved source has no original record")
        groups.setdefault(observation.source, []).append(observation)
    chunks: list[RetrievedChunk] = [
        {
            "chunk_id": originals[source],
            "raw_text": texts[source],
            "source": source,
            "observation_ids": [item.observation_id for item in items],
            "claim_ids": sorted({claim_id(item.claim) for item in items}),
        }
        for source, items in groups.items()
    ]
    validate_chunks(observations, chunks)
    return chunks


async def prepare_generation(
    observations: Sequence[Observation],
    *,
    question: str,
    estimator: DependencyEstimatorConfig,
    token_budget: int = 600,
    chunks: Sequence[RetrievedChunk] | None = None,
    evaluation: ContextEvaluation | None = None,
    preparation: PreparationOptions | None = None,
    config: OmneumClientConfig | None = None,
    server: StdioServerParameters | None = None,
) -> GenerationInput:
    if config is None and server is None:
        with example_deployment() as deployment:
            return await prepare_generation(
                observations, question=question, estimator=estimator, token_budget=token_budget,
                chunks=chunks, evaluation=evaluation, preparation=preparation,
                config=deployment[0], server=deployment[1],
            )
    if config is None or server is None:
        raise TypeError("config and server must be supplied together")
    options = PreparationOptions(token_budget=token_budget) if preparation is None else preparation
    chunks = collect_chunks(observations) if chunks is None else list(chunks)
    validate_chunks(observations, chunks)
    diagnostics: dict[str, Any] = {}
    selection_options = {
        "local_relevance": "bm25", "strategy": "coverage_support_density",
        "token_cost_exponent": 1.0, "complementary_evidence": True,
        "include_dependencies": True, "query_evaluation": "full",
    }
    async with open_stdio_client(config, server) as client:
        if evaluation is None:
            evaluation = await client.evaluate_context(observations, estimator=estimator)
        prepared = await client.prepare_context(
            observations, chunks, estimator=estimator, token_budget=options.token_budget, evaluation=evaluation,
            include_telemetry=options.include_telemetry, collect_telemetry=options.collect_telemetry,
            user_query=question, query_diagnostics=diagnostics, **selection_options,
        )
    by_id = {chunk["chunk_id"]: chunk for chunk in chunks}
    selected = [by_id[identifier] for identifier in prepared["packed_chunk_ids"]]
    structural = [
        {"claim_id": claim_id(item.claim), "attribute": item.claim.attribute,
         "value": item.claim.value, "supporting_source_count": item.supporting_source_count,
         "estimated_independent_support": item.estimated_independent_support_count}
        for item in sorted(evaluation.claim_support, key=lambda item: (item.claim.attribute, claim_id(item.claim)))
    ]
    comparison = None
    if options.compare:
        raw = reconstruct_context(evaluation, chunks, token_budget=options.token_budget, strategy="retrieval")
        comparison = {"raw_rag": raw}
    return {
        "evaluation": evaluation,
        "question": question,
        "configuration": {**asdict(options), **selection_options},
        "structural_evaluation": structural,
        "comparison": comparison,
        "retrieved_chunks": chunks,
        "prepared_context": prepared,
        "messages": generation_messages(question, prepared["context"], selected),
        "query_diagnostics": diagnostics,
    }
