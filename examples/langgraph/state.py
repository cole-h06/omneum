from __future__ import annotations

from operator import add
from typing import Annotated, NotRequired, TypedDict

from omneum import ContextEvaluation, Observation
from examples.langgraph.routing.selection import SelectedClaim


class ObservationBatch(TypedDict):

    agent: str
    observations: tuple[Observation, ...]


class WorkflowState(TypedDict):

    question: str
    observation_batches: Annotated[list[ObservationBatch], add]
    observations: NotRequired[tuple[Observation, ...]]
    context_evaluation: NotRequired[ContextEvaluation]
    answer: NotRequired[str]
    selected_claims: NotRequired[tuple[SelectedClaim, ...]]
    retry_count: NotRequired[int]
    routing_history: NotRequired[tuple[str, ...]]