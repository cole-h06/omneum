import json
from pathlib import Path

from .tier1_competitors import provider_ranks, aggregate


BASE=Path(__file__).parent


def test_cached_provider_models_and_complete_pools():
    ranks=provider_ranks(BASE/'results/question-aware-release-v1')
    assert len(ranks)==168
    assert len([k for k in ranks if k[1]=='cohere'])==24
    for key,r in ranks.items():
        case=json.loads((BASE/'canonical/cases'/key[0]/'case.json').read_text())
        assert set(r['order'])=={'chunk-'+c['source_id'] for c in case['candidates']}
        assert (r['scores'] is not None)==(key[1]=='cohere')


def test_provider_latency_is_not_synthesized_from_replay_samples():
    fields=['evidence_retention','actual_context_tokens','context_reduction',
            'supporting_passage_claim_coverage','independent_evidence_coverage',
            'source_precision','source_recall','tokenizer_tokens']
    cells=[dict(case_id='a',method='claude',budget=64,**{k:.5 for k in fields})]
    runs=[dict(method='claude',selection_ms=v) for v in [1,2,3,4,5]]
    history=[dict(method='claude',seconds=2),dict(method='claude',seconds=4)]
    result=aggregate(cells,runs,history)['claude']
    assert result['selection_ms']==dict(n=5,p50=3,p95=4.8)
    assert result['historical_provider_seconds']==dict(n=2,p50=3,p95=3.9)
    assert result['historical_provider_cost_usd'] is None
    assert result['new_api_cost_usd']==0


def test_raw_reference_is_not_mixed_with_budgeted_runs():
    fields=['evidence_retention','actual_context_tokens','context_reduction',
            'supporting_passage_claim_coverage','independent_evidence_coverage',
            'source_precision','source_recall','tokenizer_tokens']
    cells=[dict(case_id='a',method=m,budget=b,**{k:.5 for k in fields})
           for m,b in [('raw_full',None),('raw_budget',64)]]
    result=aggregate([r for r in cells if r['budget']==64],[],[])
    assert set(result)=={'raw_budget'}
