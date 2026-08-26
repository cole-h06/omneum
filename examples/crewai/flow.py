from crewai.flow.flow import Flow, and_, listen, start

from examples.enterprise.agents.api import api_agent
from examples.enterprise.agents.documents import documents_agent
from examples.enterprise.agents.research import research_agent
from examples.enterprise.agents.search import search_agent
from examples.enterprise.agents.sql import sql_agent
from examples.enterprise.config import example_deployment
from examples.enterprise.workflow.run import estimator_config, render_result
from omneum import ContextMapper, open_stdio_client

from .state import WorkflowState


class EnterpriseFlow(Flow[WorkflowState]):
    @start()
    def retrieve_documents(self):
        self.state.document_observations = documents_agent()

    @start()
    def retrieve_research(self):
        self.state.research_observations = research_agent()

    @start()
    def retrieve_sql(self):
        self.state.sql_observations = sql_agent()

    @start()
    def retrieve_api(self):
        self.state.api_observations = api_agent()

    @start()
    def retrieve_search(self):
        self.state.search_observations = search_agent()

    @listen(
        and_(
            retrieve_documents,
            retrieve_research,
            retrieve_sql,
            retrieve_api,
            retrieve_search,
        )
    )
    def merge_observations(self):
        # Keep the same order as the canonical workflow so both examples
        # produce stable, directly comparable output.
        self.state.observations = (
            *self.state.document_observations,
            *self.state.research_observations,
            *self.state.sql_observations,
            *self.state.api_observations,
            *self.state.search_observations,
        )
        return self.state.observations

    @listen(merge_observations)
    async def evaluate_assertion(self):
        with example_deployment() as (config, server):
            async with open_stdio_client(config, server) as client:
                mapper = ContextMapper(
                    source=lambda x: x.source,
                    entity_namespace=lambda x: x.claim.entity_namespace,
                    entity=lambda x: x.claim.entity,
                    attribute=lambda x: x.claim.attribute,
                    value=lambda x: x.claim.value,
                    assertion_id=lambda x: x.assertion_id,
                    observed_at=lambda x: x.observed_at,
                    source_modified_at=lambda x: x.source_modified_at,
                    upstream_sources=lambda x: x.upstream_sources,
                    cited_sources=lambda x: x.cited_sources,
                    parent_assertion_ids=lambda x: x.parent_assertion_ids,
                    retrievals=lambda x: x.retrievals,
                    signals={
                        name: lambda x, name=name: x.dependency_signals.get(
                            name
                        )
                        for name in (
                            "upstream",
                            "citation",
                            "assertion_lineage",
                            "ownership",
                            "temporal",
                            "graph",
                            "retrieval",
                        )
                    },
                )

                result = await client.evaluate_mapped(
                    self.state.observations,
                    mapper,
                    estimator=estimator_config(),
                )

        self.state.assertion_evaluation = result
        return result

    @listen(evaluate_assertion)
    def render_answer(self):
        self.state.answer = render_result(self.state.assertion_evaluation)
        return self.state.answer