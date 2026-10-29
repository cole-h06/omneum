"""Question-only selection must expose why unused budget buys no utility."""
import asyncio
from datetime import datetime, timezone

import pytest

from omneum import Claim, Observation, OmneumClient, Source
from omneum.client import _evaluate_context
from omneum.context_selection import claim_id
from benchmarks.context_selection.config import estimator_config


@pytest.mark.parametrize("question", [None, "What is the retention period?"])
def test_no_discovery_plan_still_publishes_selection_trace(monkeypatch, question):
    claim = Claim("service", "account", "retention_period", "30 days")
    source = Source("web_document", "https://evidence.example")
    observations = (Observation("rule", source, claim,
                                observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc)),)
    chunks = [
        {"chunk_id": "rule", "raw_text": "Retention is 30 days.",
         "claim_ids": [claim_id(claim)]},
        {"chunk_id": "qualification", "raw_text": "Retention is 30 days; legal holds suspend deletion.",
         "claim_ids": [claim_id(claim)]},
    ]
    # Exercise the SDK selection boundary with real inference and no transport.
    client = object.__new__(OmneumClient)
    client._local_persistence = None
    async def evaluate(self, values, **options):
        assert options.pop("exact_equivalences") == ()
        return _evaluate_context(values, **options)
    monkeypatch.setattr(OmneumClient, "_evaluate_context", evaluate)

    async def run():
        options = dict(estimator=estimator_config(), token_budget=1000,
                       question=question, count_tokens=len)
        before = await client.prepare_context(observations, chunks, **options)
        diagnostics = {}
        after = await client.prepare_context(observations, chunks,
                                              query_diagnostics=diagnostics, **options)
        assert before == after
        assert after["packed_chunk_ids"] == ["rule"]
        assert diagnostics["selected_chunk_ids"] == after["packed_chunk_ids"]
        assert diagnostics["reconstructed_context_tokens"] == len(after["context"])
        assert diagnostics["eligible_unselected_chunks"] == [
            {"chunk_id": "qualification", "reason": "not_selected_by_packer"}]
        final = diagnostics["utility_trace"][-1]["candidates"]
        assert len(final) == 1
        assert final[0]["chunk_id"] == "qualification"
        assert final[0]["feasible"]
        assert final[0]["marginal_gain"] == final[0]["utility"] == 0
        assert diagnostics["selection_scores"][0]["marginal_gain"] > 0
    asyncio.run(run())
