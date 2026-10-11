import asyncio

import pytest

pytest.importorskip("langgraph")

from examples.enterprise.workflow.run import QUESTION
from examples.langgraph.graph import build_graph
from examples.langgraph.nodes import _AGENT_ORDER


def test_langgraph_workflow(example_daemon):
    graph = build_graph()

    state = asyncio.run(
        graph.ainvoke(
            {
                "question": QUESTION,
                "observation_batches": [],
            }
        )
    )

    assert len(state["observation_batches"]) == 5
    assert [
        batch["agent"] for batch in sorted(
            state["observation_batches"],
            key=lambda batch: _AGENT_ORDER[batch["agent"]],
        )
    ] == ["documents", "research", "sql", "api", "search"]

    expected = tuple(
        observation
        for batch in sorted(
            state["observation_batches"],
            key=lambda batch: _AGENT_ORDER[batch["agent"]],
        )
        for observation in batch["observations"]
    )
    assert state["observations"] == expected

    evaluation = state["context_evaluation"]

    assert len(evaluation.source_reliability) == 6
    assert len(evaluation.claim_support) == 6
    assert len(evaluation.pairwise_dependencies) == 15
    assert evaluation.evaluation_latency_ms is not None
    assert evaluation.evaluation_latency_ms >= 0

    assert "Application decision: EVALUATION COMPLETE" in state["answer"]
    assert "Omneum Evaluation" in state["answer"]
    assert "Conflicting values:" in state["answer"]
    assert "dependency signals" in state["answer"]
