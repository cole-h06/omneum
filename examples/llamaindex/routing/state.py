"""Per-run state carried by native Workflow events."""

from pydantic import BaseModel, ConfigDict

from examples.langgraph.routing.policy import RoutingDecision
from examples.langgraph.routing.selection import SelectedClaim
from omneum import ContextEvaluation, Observation


class RoutingState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    scenario: str
    initial_observation_count: int
    observations: tuple[Observation, ...]
    context_evaluation: ContextEvaluation | None = None
    decision: RoutingDecision | None = None
    retry_count: int = 0
    routing_history: tuple[str, ...] = ()
    selected_claims: tuple[SelectedClaim, ...] = ()
    answer: str = ""
