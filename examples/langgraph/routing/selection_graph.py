from functools import partial

from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, START, StateGraph

from examples.langgraph.nodes import evaluate_context, prepare_context, render_answer
from examples.langgraph.state import WorkflowState

from .selection import select_context


def select_claims(state: WorkflowState) -> dict:
    return {
        "selected_claims": select_context(state["context_evaluation"]),
    }


async def generate_selected(state: WorkflowState, *, model: BaseChatModel | None = None) -> dict:
    result = await render_answer(state, model=model)
    if model is None:
        result["answer"] = "Application decision: EVALUATION COMPLETE\n" + result["answer"]
    return result

def build_selection_graph(*, model: BaseChatModel | None = None):
    graph = StateGraph(WorkflowState)

    graph.add_node("evaluate_context", evaluate_context)
    graph.add_node("select_context", select_claims)
    graph.add_node("generate", partial(generate_selected, model=model))
    graph.add_node("prepare_context", prepare_context)

    graph.add_edge(START, "evaluate_context")
    graph.add_edge("evaluate_context", "select_context")
    graph.add_edge("select_context", "prepare_context")
    graph.add_edge("prepare_context", "generate")
    graph.add_edge("generate", END)

    return graph.compile()
