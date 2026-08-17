from typing import Any

from pydantic import BaseModel, ConfigDict

from omneum import Observation


class WorkflowState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    question: str = ""

    document_observations: tuple[Observation, ...] = ()
    research_observations: tuple[Observation, ...] = ()
    sql_observations: tuple[Observation, ...] = ()
    api_observations: tuple[Observation, ...] = ()
    search_observations: tuple[Observation, ...] = ()

    observations: tuple[Observation, ...] = ()
    assertion_evaluation: Any | None = None
    answer: str = ""