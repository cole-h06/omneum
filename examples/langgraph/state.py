from __future__ import annotations

from operator import add
from typing import Annotated, NotRequired, TypedDict

from omneum import ContextEvaluation, Observation
from examples.langgraph.routing.selection import SelectedClaim
from examples.context_preparation import GenerationInput, PreparationOptions
from examples.enterprise.workflow.retrieval import RetrievedChunk


class ObservationBatch(TypedDict):

    agent: str
    observations: tuple[Observation, ...]


class WorkflowState(TypedDict):

    question: str
    observation_batches: Annotated[list[ObservationBatch], add]
    observations: NotRequired[tuple[Observation, ...]]
    context_evaluation: NotRequired[ContextEvaluation]
    answer: NotRequired[str]
    generation: NotRequired[GenerationInput]
    retrieved_chunks: NotRequired[list[RetrievedChunk]]
    preparation: NotRequired[PreparationOptions]
    token_budget: NotRequired[int]
    selected_claims: NotRequired[tuple[SelectedClaim, ...]]
    retry_count: NotRequired[int]
    routing_history: NotRequired[tuple[str, ...]]
