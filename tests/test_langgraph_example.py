import asyncio
import json
from dataclasses import replace

import pytest

pytest.importorskip("langgraph")

from examples.enterprise.workflow.run import QUESTION
from examples.langgraph.graph import build_graph
from examples.langgraph.nodes import _AGENT_ORDER
from examples.context_preparation import collect_chunks
from omneum.context_selection import token_count
from omneum import OmneumClient, Source


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

    generation = state["generation"]
    prepared = generation["prepared_context"]
    assert generation["retrieved_chunks"] == collect_chunks(expected)
    assert prepared["context"] in generation["messages"][1]["content"]
    assert generation["messages"][1]["content"] in state["answer"]
    assert token_count(prepared["context"]) == prepared["selection"]["selected_tokens"] <= 600
    assert generation["query_diagnostics"]["relevance_source"] == "bm25"
    for chunk in generation["retrieved_chunks"]:
        if chunk["chunk_id"] in prepared["packed_chunk_ids"]:
            assert chunk["raw_text"] in generation["messages"][1]["content"]
        else:
            assert chunk["raw_text"] not in generation["messages"][1]["content"]
    assert "Omneum Evaluation" not in generation["messages"][1]["content"]


@pytest.mark.parametrize("budget", [0, 200])
def test_native_preparation_budget_and_sdk_boundary(budget, example_daemon, monkeypatch):
    from omneum import context_selection
    from omneum.mcp import ClientSession

    preparations = []
    reconstructions = []
    requests = []
    prepare = OmneumClient.prepare_context
    reconstruct = context_selection.reconstruct_context
    call_tool = ClientSession.call_tool

    async def record_prepare(self, observations, chunks, **kwargs):
        preparations.append((observations, chunks, kwargs))
        return await prepare(self, observations, chunks, **kwargs)

    def record_reconstruct(*args, **kwargs):
        reconstructions.append((args, kwargs))
        return reconstruct(*args, **kwargs)

    async def record_tool(self, name, arguments=None, **kwargs):
        if name == "evaluate_context":
            requests.append(arguments)
        return await call_tool(self, name, arguments, **kwargs)

    monkeypatch.setattr(OmneumClient, "prepare_context", record_prepare)
    monkeypatch.setattr(context_selection, "reconstruct_context", record_reconstruct)
    monkeypatch.setattr(ClientSession, "call_tool", record_tool)
    state = asyncio.run(build_graph().ainvoke({
        "question": QUESTION, "observation_batches": [], "token_budget": budget,
    }))
    generation = state["generation"]
    prepared = generation["prepared_context"]
    assert len(preparations) == len(reconstructions) == 1
    assert len(requests) == 1
    observations, chunks, options = preparations[0]
    assert observations == state["observations"]
    assert options["user_query"] == QUESTION
    assert options["local_relevance"] == "bm25"
    assert options["complementary_evidence"] is True
    assert generation["query_diagnostics"]["evaluation_scope"] == "full"
    assert token_count(prepared["context"]) == prepared["selection"]["selected_tokens"] <= budget
    assert prepared["context"] in generation["messages"][1]["content"]
    json.dumps(prepared, allow_nan=False)
    for chunk in chunks:
        assert all(json.dumps(chunk["raw_text"]) not in json.dumps(request) for request in requests)
        if chunk["chunk_id"] in prepared["packed_chunk_ids"]:
            assert chunk["raw_text"] in generation["messages"][1]["content"]
        else:
            assert chunk["raw_text"] not in generation["messages"][1]["content"]
    if budget == 0:
        assert prepared["context"] == ""
        assert prepared["packed_chunk_ids"] == []
    repeated = asyncio.run(build_graph().ainvoke({
        "question": QUESTION, "observation_batches": [], "token_budget": budget,
    }))
    assert repeated["generation"]["prepared_context"] == prepared


def test_shared_retry_records_and_source_validation():
    from examples.enterprise.workflow.run import collect_observations
    from examples.langgraph.routing.retrieval import retrieve_additional_evidence, retrieval_record

    observations = retrieve_additional_evidence(
        ("input_data_policy", "provider_retention"), strategy="retrieve_support",
    )
    chunks = collect_chunks(observations)
    assert len(chunks) == 1
    assert len(chunks[0]["claim_ids"]) == len(chunks[0]["observation_ids"]) == 2
    assert json.loads(chunks[0]["raw_text"]) == retrieval_record("retrieve_support", 1)
    for item in observations:
        assert json.loads(chunks[0]["raw_text"])["controls"][item.claim.attribute] == item.claim.value
    unknown = replace(collect_observations()[0], source=Source("web_document", "https://unknown.example"))
    with pytest.raises(ValueError, match="original record"):
        collect_chunks([unknown])
