from .agents.api import api_agent
from .agents.documents import document_agent
from .agents.research import research_agent
from .agents.search import search_agent
from .agents.sql import sql_agent
from .extraction.schema import SourceMetadata


SOURCES = (
    SourceMetadata(
        source_id="research_agent",
        display_name="Research Agent",
        owner_id="research_lab",
    ),
    SourceMetadata(
        source_id="search_agent",
        display_name="Search Agent",
        owner_id="search_vendor",
    ),
    SourceMetadata(
        source_id="sql_agent",
        display_name="SQL Agent",
        owner_id="commerce_platform",
    ),
    SourceMetadata(
        source_id="document_agent",
        display_name="Document Agent",
        owner_id="document_vendor",
    ),
    SourceMetadata(
        source_id="api_agent",
        display_name="API Agent",
        owner_id="commerce_platform",
    ),
)


DEPENDENCY_WEIGHTS = {
    "upstream": 0.25,
    "citation": 0.20,
    "assertion_lineage": 0.20,
    "ownership": 0.10,
    "temporal": 0.10,
    "graph": 0.15,
    "retrieval": 0.0,
}


AGENTS = (
    research_agent,
    search_agent,
    sql_agent,
    document_agent,
    api_agent,
)


def load_dataset():

    observations = []

    for agent in AGENTS:

        result = agent()

        observations.extend(result.observations)

    validate_dataset(
        SOURCES,
        observations,
    )

    return SOURCES, observations


def validate_dataset(sources, observations):
    from omneum.dependency import estimate_dependencies
    from ....adapters.observations import estimator, to_observations

    if {source.source_id for source in sources} != {item.source_id for item in observations}:
        raise ValueError("every source must have an observation")
    values = to_observations(sources, observations)
    estimate_dependencies(
        tuple(dict.fromkeys(item.source for item in values)),
        values,
        estimator(DEPENDENCY_WEIGHTS),
    )
