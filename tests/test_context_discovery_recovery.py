"""Expanded discovery is a priority neighborhood, not a permanent exclusion."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from omneum.context_selection import map_chunks, reconstruct, select_chunks, claim_id


def fixture():
    chunks = [dict(chunk_id=k, raw_text='Original '+k+'\r\n😀', claim_ids=[claim])
              for k, claim in [('seed','x'),('copy','x'),('independent','x'),
                               ('qualification','y'),('zero','z')]]
    chunks[0]['raw_text'] += ' detailed initial evidence' * 6
    support = dict(x=1., y=.5, z=0.)
    terms = {k:{claim:(group,mass)} for k,claim,group,mass in [
        ('seed','x',('origin',),.7),('copy','x',('origin',),.7),
        ('independent','x',('other',),.3),('qualification','y',('qualifier',),.5),
        ('zero','z',('zero',),0.)]}
    return chunks,support,terms


def select(budget=10000, deferred=('copy','independent','qualification','zero'), **options):
    chunks,support,terms=fixture()
    return select_chunks(map_chunks(chunks,support),support,budget,'coverage_support_density',
        count_tokens=lambda s:len(s.encode()),token_cost_exponent=1,
        claim_source_utility=terms,_deferred_chunk_ids=deferred,**options)


def test_residual_budget_recovers_independent_and_complementary_not_dependent_duplicates():
    result=select()
    assert result['selection_order']==['seed','qualification','independent']
    assert set(result['selected_chunk_ids'])=={'seed','independent','qualification'}
    assert result['covered_claim_ids']==['x','y']
    assert sum(r['marginal_gain'] for r in result['selection_scores'])==pytest.approx(1.5)
    assert set(result['_recovery_considered_chunk_ids'])=={'copy','independent','qualification','zero'}
    assert result['token_usage']<10000  # Capacity alone cannot justify another passage.


def test_initial_neighborhood_remains_first_under_tight_budget():
    chunks,support,_=fixture();mapping=map_chunks(chunks,support)
    budget=len(reconstruct(mapping,['seed']).encode())
    result=select(budget)
    assert result['selected_chunk_ids']==['seed']
    assert result['token_usage']==budget


def test_no_remaining_initial_candidates_still_searches_deferred_pool():
    result=select(deferred=tuple(c['chunk_id'] for c in fixture()[0]))
    assert set(result['selected_chunk_ids'])=={'copy','qualification','independent'}


def test_zero_primary_utility_does_not_hide_positive_deferred_evidence():
    result=select(deferred=('seed','copy','independent','qualification'))
    assert set(result['selected_chunk_ids'])=={'copy','qualification','independent'}
    assert 'zero' not in result['selected_chunk_ids']


def test_zero_and_negative_regularized_utilities_do_not_fill_budget():
    chunks=[dict(chunk_id=k,raw_text=k,claim_ids=[k]) for k in ('a','b')]
    for support,penalty in [(dict(a=0.,b=0.),0.),(dict(a=.1,b=.1),1.)]:
        result=select_chunks(map_chunks(chunks,support),support,1000,'coverage_support_density',
            count_tokens=len,token_penalty=penalty,_deferred_chunk_ids=('b',))
        assert result['selected_chunk_ids']==[]


@pytest.mark.parametrize('budget',[0,1,30,50,80,130,10000])
def test_deterministic_original_reconstruction_and_exact_utf8_budget(budget):
    chunks,support,_=fixture();before=deepcopy(chunks)
    result=select(budget)
    assert result==select(budget,deferred=('zero','qualification','independent','copy'))
    assert result['context']==reconstruct(map_chunks(chunks,support),result['selected_chunk_ids'])
    assert result['token_usage']==len(result['context'].encode())<=budget
    assert chunks==before


def test_nonadditive_whole_context_token_checks():
    chunks,support,terms=fixture()
    counter=lambda s:len(s.encode())+17*s.count('\n\n')
    result=select_chunks(map_chunks(chunks,support),support,100,'coverage_support_density',
        count_tokens=counter,token_cost_exponent=1,claim_source_utility=terms,
        _deferred_chunk_ids=('copy','independent','qualification','zero'))
    assert counter(result['context'])==result['token_usage']<=100


def test_unknown_deferred_id_rejected():
    with pytest.raises(ValueError,match='candidate pool'):
        select(deferred=('missing',))


def test_recovery_preserves_accepted_density_boundary_without_filling_capacity():
    chunks,support,terms=fixture()
    chunks[0]['raw_text']='s'
    trace=[]
    result=select_chunks(map_chunks(chunks,support),support,10000,'coverage_support_density',
        count_tokens=len,token_cost_exponent=1,claim_source_utility=terms,
        _deferred_chunk_ids=('copy','independent','qualification','zero'),selection_trace=trace)
    assert result['selected_chunk_ids']==['seed']
    assert result['_recovery_utility_floor']==result['selection_scores'][0]['regularized_utility']
    recovery=[s for s in trace if 'recovery_utility_floor' in s][-1]
    positive=[c for c in recovery['candidates'] if c['marginal_gain']>0]
    assert positive and all(not c['passes_recovery_floor'] for c in positive)


def test_sdk_expanded_recovers_but_explicit_top_k_remains_a_hard_restriction():
    from omneum import Claim, Observation, Source, open_stdio_client
    from benchmarks.context_selection.deployment import benchmark_deployment
    from benchmarks.context_selection.config import estimator_config
    observations=[Observation(k,Source('web_document','https://'+k+'.example'),
        Claim('device',k,'state','ready'),observed_at=datetime(2026,1,1,tzinfo=timezone.utc))
        for k in ('a','b','c','d')]
    chunks=[dict(chunk_id=o.observation_id,source=o.source,raw_text='Original '+o.observation_id,
                 claim_ids=[claim_id(o.claim)]) for o in observations]
    chunks[0]['raw_text'] += ' detailed original evidence' * 6
    async def run():
        with benchmark_deployment() as (config,server):
            async with open_stdio_client(config,server,local_persistence=None) as client:
                evaluations=[]
                for policy in ('expanded','top_k','all'):
                    diagnostics={}
                    result=await client.prepare_context(observations,chunks,estimator=estimator_config(),
                        token_budget=1000,count_tokens=len,strategy='coverage_support_density',
                        complementary_evidence=True,token_cost_exponent=1,
                        chunk_relevance=dict(a=1.,b=.8,c=.6,d=0.),relevance_score_type='normalized',
                        candidate_discovery=policy,candidate_count=1,expansion_depth=1,
                        query_evaluation='full',query_diagnostics=diagnostics)
                    assert set(result['packed_chunk_ids'])==({'a'} if policy=='top_k' else {'a','b','c'})
                    assert len(result['context'])<=1000
                    if policy=='expanded':
                        assert diagnostics['initial_eligible_chunk_ids']==['a']
                        assert diagnostics['recovered_chunk_ids']==['b','c']
                        assert diagnostics['excluded_chunks']==[]
                    evaluations.append(result['evaluation'])
                assert evaluations[0]==evaluations[1]==evaluations[2]
    asyncio.run(run())
