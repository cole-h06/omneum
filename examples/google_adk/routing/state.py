from dataclasses import dataclass, field
from typing import Any

from google.genai import types

from examples.context_preparation import PreparationOptions
from omneum import ContextEvaluation, Observation
from examples.enterprise.workflow.run import QUESTION
from examples.langgraph.routing.policy import RoutingDecision
from examples.langgraph.routing.selection import SelectedClaim


@dataclass
class RoutingState:
    scenario: str
    initial_observation_count: int
    observations: tuple[Observation, ...]
    context_evaluation: ContextEvaluation | None = None
    decision: RoutingDecision | None = None
    retry_count: int = 0
    routing_history: tuple[str, ...] = ()
    selected_claims: tuple[SelectedClaim, ...] = ()
    stage_history: tuple[str, ...] = ()
    answer: str = ""
    preparation: PreparationOptions = field(default_factory=PreparationOptions)
    question: str = QUESTION
    generation: dict[str, Any] | None = None
    retrieved_chunks: list[dict[str, Any]] = field(default_factory=list)
    generation_content: types.Content | None = None
