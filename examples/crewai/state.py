from typing import Any

from crewai import Task
from pydantic import BaseModel, ConfigDict, Field

from examples.context_preparation import PreparationOptions
from omneum import ContextEvaluation, Observation
from examples.enterprise.workflow.run import QUESTION


class WorkflowState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    preparation: PreparationOptions = Field(default_factory=PreparationOptions)
    question: str = QUESTION

    document_observations: tuple[Observation, ...] = ()
    research_observations: tuple[Observation, ...] = ()
    sql_observations: tuple[Observation, ...] = ()
    api_observations: tuple[Observation, ...] = ()
    search_observations: tuple[Observation, ...] = ()

    observations: tuple[Observation, ...] = ()
    context_evaluation: ContextEvaluation | None = None
    answer: str = ""
    generation: dict[str, Any] | None = None
    retrieved_chunks: list[dict[str, Any]] = Field(default_factory=list)
    generation_task: Task | None = None
