import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

from omneum import (
    Claim, OmneumClient, OmneumClientConfig, Source,
    open_stdio_client, reconstruct_context,
)
from omneum.agent_result import _serialize_context_result
from omneum.context_selection import STRATEGIES, claim_id, token_count
from omneum.mcp import ClientSession, StdioServerParameters
from stdio_state import isolated_deployment_environment
from test_client import DEPLOYMENT_ID, PRIVATE_KEY
from test_client_evaluation import estimator, make_observation


def test_evaluate_context_with_local_chunks(tmp_path, monkeypatch):
    majority = Claim("service", "Product", "return_window", "30 days")
    minority = Claim("service", "Product", "return_window", "14 days")
    observations = tuple(
        make_observation(f"observation-{index}", Source("web_document", url), claim)
        for index, (url, claim) in enumerate((
            ("https://a.example", majority),
            ("https://b.example", majority),
            ("https://c.example", minority),
        ))
    )
    chunks = [
        {"chunk_id": "local-chunk-conflict", "raw_text": "Private conflicting passage: 14 days.", "claim_ids": [claim_id(minority)]},
        {"chunk_id": "local-chunk-tie-b", "raw_text": " \tOriginal passage: 30 days.\r\n😀 ", "claim_ids": [claim_id(majority)]},
        {"chunk_id": "local-chunk-tie-a", "raw_text": " \tOriginal passage: 30 days.\r\n😀 ", "claim_ids": [claim_id(majority)]},
    ]
    before = deepcopy(chunks)
    calls = []
    evaluations = []
    original_call = ClientSession.call_tool
    original_evaluate = OmneumClient._evaluate_context

    async def tracked_call(self, name, arguments=None, *args, **kwargs):
        calls.append((name, deepcopy(arguments)))
        return await original_call(self, name, arguments, *args, **kwargs)

    async def tracked_evaluate(self, *args, **kwargs):
        result = await original_evaluate(self, *args, **kwargs)
        evaluations.append(result)
        return result

    monkeypatch.setattr(ClientSession, "call_tool", tracked_call)
    monkeypatch.setattr(OmneumClient, "_evaluate_context", tracked_evaluate)

    async def run():
        environment, public_key, _ = isolated_deployment_environment(tmp_path, DEPLOYMENT_ID, PRIVATE_KEY)
        config = OmneumClientConfig(
            deployment_id=DEPLOYMENT_ID,
            voprf_key_version=1,
            voprf_mode="voprf",
            voprf_ciphersuite="ristretto255-SHA512",
            linkage_encoding_version=1,
            voprf_public_key=public_key,
        )
        server = StdioServerParameters(
            command=sys.executable, args=["-m", "omneum.server"],
            cwd=Path(__file__).parents[1], env=environment,
        )
        async with open_stdio_client(config, server, local_persistence=None) as client:
            baseline = await client._evaluate_context(observations, estimator=estimator())
            assert baseline.claim_support[0].conflicting_claims
            question = "What is the return window for Product?"
            prepared = await client.prepare_context(
                observations, chunks, estimator=estimator(), token_budget=100,
                question=question,
            )
            direct = reconstruct_context(
                baseline, chunks, token_budget=100, question=question,
            )
            assert prepared["packed_chunk_ids"] == direct["selected_chunk_ids"]
            assert prepared["context"] == direct["context"]
            evaluated = await client.evaluate_context_with_chunks(
                observations, chunks, estimator=estimator(), token_budget=100,
                question=question,
            )
            assert evaluated["selected_chunk_ids"] == direct["selected_chunk_ids"]
            no_question = reconstruct_context(baseline, chunks, token_budget=100)
            empty_question = await client.prepare_context(
                observations, chunks, estimator=estimator(), token_budget=100,
                question="  ",
            )
            assert empty_question["packed_chunk_ids"] == no_question["selected_chunk_ids"]
            assert empty_question["context"] == no_question["context"]
            cases = (
                (0, token_count), (20, token_count), (100, token_count),
                (100, lambda text: len(text.encode("utf-8"))),
            )
            for strategy in STRATEGIES:
                if strategy in ("coverage_answer", "coverage_support_nonlinear"):
                    with pytest.raises(ValueError, match="requires caller"):
                        await client.prepare_context(observations, chunks, estimator=estimator(),
                            token_budget=100, strategy=strategy)
                    continue
                options = {}
                if strategy == "coverage_support_query":
                    options["claim_relevance"] = {claim_id(c.claim): 1.0 for c in baseline.claim_support}
                for budget, counter in cases:
                    result = await client.prepare_context(
                        observations, chunks, estimator=estimator(), token_budget=budget,
                        strategy=strategy, count_tokens=counter, **options,
                    )
                    assert evaluations[-1] == baseline
                    assert evaluations[-1].source_reliability == baseline.source_reliability
                    assert evaluations[-1].claim_support == baseline.claim_support
                    selected = reconstruct_context(
                        baseline, chunks, token_budget=budget, strategy=strategy, count_tokens=counter, **options,
                    )
                    counter_name = "unicode_word_punctuation_proxy" if counter is token_count else "custom"
                    assert result == _serialize_context_result({"evaluation": baseline, **selected}, token_counter=counter_name)
                    assert result["selection"]["selected_tokens"] == counter(result["context"]) <= budget
                    assert result["selection"]["token_budget"] == budget
                    assert result["selection"]["input_tokens"] == counter("\n\n".join(
                        f"[{item['chunk_id']}]\n{item['raw_text']}" for item in chunks))
                    assert result["context"] == "\n\n".join(
                        f"[{item['chunk_id']}]\n{item['raw_text']}" for item in result["chunks"]
                    )
                    assert [item["chunk_id"] for item in result["chunks"]] == result["packed_chunk_ids"]
                    scores = [item["score"] for item in result["chunks"]]
                    assert scores == sorted(scores, reverse=True)
                    chosen = set(result["packed_chunk_ids"])
                    assert selected["mapping"]["chunk_text"] == {
                        item["chunk_id"]: item["raw_text"] for item in chunks if item["chunk_id"] in chosen
                    }
                    if budget == 100 and strategy in ("max_support", "mean_support") and counter is token_count:
                        assert result["packed_chunk_ids"] == [
                            "local-chunk-tie-b", "local-chunk-tie-a", "local-chunk-conflict",
                        ]
            empty = await client.prepare_context(observations, [], estimator=estimator(), token_budget=0)
            assert empty["chunks"] == []
            assert empty["context"] == ""
            assert empty["selection"]["selected_tokens"] == 0
            with pytest.raises(ValueError, match="observation graph must not be empty"):
                await client.prepare_context([], [], estimator=estimator(), token_budget=0)
            for invalid, message in (([*chunks, chunks[0]], "duplicate chunk ID"), (chunks[1:], "evaluated claim has no chunk mapping")):
                with pytest.raises(ValueError, match=message):
                    await client.prepare_context(observations, invalid, estimator=estimator(), token_budget=100)

    asyncio.run(run())
    assert chunks == before
    wire = json.dumps(calls)
    assert all(item["raw_text"] not in wire for item in chunks)
    assert all(item["chunk_id"] not in wire for item in chunks)
    requests = [arguments for name, arguments in calls if name == "evaluate_context"]
    assert requests
    assert all(request == requests[0] for request in requests)
    assert all(set(item) == {"source_id", "attribute_id", "claim_id"} for item in requests[0]["assertions"])
