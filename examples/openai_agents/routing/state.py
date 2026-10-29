from dataclasses import dataclass, field

from examples.context_preparation import PreparationOptions
from omneum import ContextEvaluation, Observation
from examples.context_preparation import GenerationInput
from examples.enterprise.workflow.retrieval import RetrievedChunk
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
    tool_history: tuple[str, ...] = ()
    answer: str = ""
    preparation: PreparationOptions = field(default_factory=PreparationOptions)
    question: str = QUESTION
    generation: GenerationInput | None = None
    retrieved_chunks: list[RetrievedChunk] = field(default_factory=list)
