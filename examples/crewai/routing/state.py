from typing import Any

from crewai import Task
from pydantic import BaseModel, ConfigDict, Field

from examples.context_preparation import PreparationOptions
from omneum import ContextEvaluation, Observation
from examples.enterprise.workflow.run import QUESTION
from examples.langgraph.routing.policy import RoutingDecision
from examples.langgraph.routing.selection import SelectedClaim


class RoutingState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    scenario: str = "diversify_sources"
    initial_observation_count: int = 0
    observations: tuple[Observation, ...] = ()
    context_evaluation: ContextEvaluation | None = None
    decision: RoutingDecision | None = None
    retry_count: int = 0
    routing_history: tuple[str, ...] = ()
    selected_claims: tuple[SelectedClaim, ...] = ()
    answer: str = ""
    preparation: PreparationOptions = Field(default_factory=PreparationOptions)
    question: str = QUESTION
    generation: dict[str, Any] | None = None
    retrieved_chunks: list[dict[str, Any]] = Field(default_factory=list)
    generation_task: Task | None = None
