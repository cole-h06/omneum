from datetime import datetime

from ..dataset import DEPENDENCY_WEIGHTS
from ..workflow.pipeline import build_pipeline

from .agents import (
    faq_agent,
    handbook_agent,
    research_agent,
    sql_agent,
    vendor_agent,
)
from .data import ORDER, SOURCES, controlled_clock, load_manifest


def build_enterprise(
    clock=controlled_clock,
    weights=None,
):

    source_modified_at = datetime.fromisoformat(
        load_manifest()["research_source_modified_at"]
    )

    def handbook_node(state):

        return {
            "results": {
                "handbook": handbook_agent(clock()),
            }
        }

    def faq_node(state):

        return {
            "results": {
                "faq": faq_agent(clock()),
            }
        }

    def sql_node(state):

        return {
            "results": {
                "sql": sql_agent(clock()),
            }
        }

    def vendor_node(state):

        return {
            "results": {
                "vendor": vendor_agent(clock()),
            }
        }

    def research_node(state):

        return {
            "results": {
                "research": research_agent(
                    state["results"]["handbook"],
                    state["results"]["vendor"],
                    source_modified_at,
                    clock(),
                ),
            }
        }

    agents = {
        "handbook": handbook_node,
        "faq": faq_node,
        "sql": sql_node,
        "vendor": vendor_node,
        "research": research_node,
    }

    return build_pipeline(
        agent_nodes=agents,
        order=ORDER,
        sources=SOURCES,
        roots=("handbook", "faq", "sql", "vendor"),
        collect_from=("faq", "sql", "research"),
        joins=((
            ("handbook", "vendor"),
            "research",
        ),),
        weights=(
            DEPENDENCY_WEIGHTS
            if weights is None
            else weights
        ),
    )


def run_enterprise(
    clock=controlled_clock,
    weights=None,
):

    workflow = build_enterprise(
        clock=clock,
        weights=weights,
    )

    state = workflow.invoke({
        "results": {},
    })

    return {
        "sources": state["sources"],
        "observations": state["observations"],
        "evaluation": state["evaluation"],
    }
