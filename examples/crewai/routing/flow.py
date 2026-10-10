from crewai.flow.flow import Flow, listen, or_, router, start

from examples.enterprise.config import example_deployment
from examples.enterprise.workflow.run import estimator_config
from examples.langgraph.routing.policy import assess_context
from examples.langgraph.routing.retrieval import retrieve_additional_evidence
from examples.langgraph.routing.scenarios import initial_observations
from examples.langgraph.routing.selection import select_context
from omneum import open_stdio_client

from .state import RoutingState


class RoutingFlow(Flow[RoutingState]):
    @start()
    def load_evidence(self):
        self.state.observations = initial_observations(self.state.scenario)
        self.state.initial_observation_count = len(self.state.observations)

    @listen(or_(load_evidence, "evidence_added"))
    async def evaluate_context(self):
        with example_deployment() as (config, server):
            async with open_stdio_client(config, server) as client:
                self.state.context_evaluation = await client.evaluate_context(
                    self.state.observations,
                    estimator=estimator_config(),
                )

    @router(evaluate_context)
    def route_context(self):
        decision = assess_context(
            self.state.context_evaluation,
            retries=self.state.retry_count,
        )
        self.state.decision = decision
        self.state.routing_history = (*self.state.routing_history, decision.route)
        return decision.route

    def _retrieve(self, strategy: str):
        known_ids = {item.observation_id for item in self.state.observations}
        additional = retrieve_additional_evidence(
            self.state.decision.attributes,
            strategy=strategy,
            attempt=self.state.retry_count + 1,
        )
        self.state.observations = (
            *self.state.observations,
            *(item for item in additional if item.observation_id not in known_ids),
        )
        self.state.retry_count += 1

    @listen("retrieve_support")
    def retrieve_support_evidence(self):
        self._retrieve("retrieve_support")

    @listen("resolve_conflicts")
    def retrieve_conflict_evidence(self):
        self._retrieve("resolve_conflicts")

    @listen("diversify_sources")
    def retrieve_diverse_evidence(self):
        self._retrieve("diversify_sources")

    @router(or_(
        retrieve_support_evidence,
        retrieve_conflict_evidence,
        retrieve_diverse_evidence,
    ))
    def reevaluate(self):
        return "evidence_added"

    @listen("generate")
    def select_claims(self):
        self.state.selected_claims = select_context(self.state.context_evaluation)

    @listen(select_claims)
    def generate_answer(self):
        self.state.answer = "\n".join([
            "Application decision: EVALUATION COMPLETE",
            "Selected context:",
            *(
                f"{claim.attribute}: {claim.value}"
                for claim in self.state.selected_claims
            ),
        ])
        return self.state.answer

    @listen("escalate")
    def escalate_answer(self):
        self.state.answer = (
            "Application decision: ESCALATE\n"
            "Evidence did not meet the routing policy."
        )
        return self.state.answer
