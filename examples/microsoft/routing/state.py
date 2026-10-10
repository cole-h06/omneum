from dataclasses import dataclass

from examples.langgraph.routing.policy import RoutingDecision
from examples.langgraph.routing.selection import SelectedClaim
from omneum import ContextEvaluation, Observation


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
    answer: str = ""