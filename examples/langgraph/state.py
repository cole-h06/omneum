from operator import add
from typing import Annotated, NotRequired, TypedDict

from omneum import AssertionEvaluation, Observation


class ObservationBatch(TypedDict):
    """Observations produced by one retrieval branch."""

    agent: str
    observations: tuple[Observation, ...]


class WorkflowState(TypedDict):
    """State shared across the LangGraph workflow."""

    question: str
    observation_batches: Annotated[list[ObservationBatch], add]
    observations: NotRequired[tuple[Observation, ...]]
    assertion_evaluation: NotRequired[AssertionEvaluation]
    answer: NotRequired[str]