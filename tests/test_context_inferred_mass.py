"""Query utility consumes converged mass; semantic grounding stays upstream."""
import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import json

import pytest

from omneum import Claim, Observation, Source
from omneum.client import _evaluate_context
from omneum.context_selection import claim_id, reconstruct_context, _inferred_coverage_terms
from omneum.extraction import _ground_chunk_observations
from benchmarks.context_selection.config import estimator_config


def fixture():
    a=Observation('a',Source('web_document','https://a.example'),Claim('device','pump','pressure',200),observed_at=datetime(2026,1,1,tzinfo=timezone.utc))
    b=replace(a,observation_id='b',source=Source('web_document','https://b.example'),parent_observation_ids=('a',))
    c=replace(a,observation_id='c',source=Source('web_document','https://c.example'),parent_observation_ids=())
    values=(a,b,c)
    return values,[dict(chunk_id=o.observation_id,raw_text='Original pressure 200 '+o.observation_id+'\r\n😀',source=o.source,claim_ids=[claim_id(o.claim)]) for o in values]


def test_cluster_mass_is_counted_once_and_qualifier_adds_distinct_coverage():
    obs,chunks=fixture();ev=_evaluate_context(obs,estimator=estimator_config())
    terms=_inferred_coverage_terms(ev,chunks);cid=claim_id(obs[0].claim)
    assert terms['a'][cid]==terms['b'][cid]
    assert terms['a'][cid][0]!=terms['c'][cid][0]
    assert terms['a'][cid][1]+terms['c'][cid][1]==pytest.approx(ev.claim_support[0].support)
    trace=[]
    result=reconstruct_context(ev,chunks,token_budget=10000,strategy='coverage_support_query',chunk_relevance=dict.fromkeys('abc',1.),_selection_trace=trace)
    assert len(result['selected_chunk_ids'])==2
    assert sum(c['marginal_gain'] for c in result['selection_scores'])==pytest.approx(ev.claim_support[0].support)
    # Same source/claim repeated in another chunk has no new support mass.
    duplicate={**chunks[0],'chunk_id':'copy','raw_text':chunks[0]['raw_text']+' duplicate'}
    result2=reconstruct_context(ev,[*chunks,duplicate],token_budget=10000,strategy='coverage_support_query',chunk_relevance=dict.fromkeys(['a','b','c','copy'],1.))
    assert 'copy' not in result2['selected_chunk_ids']
    qualification=replace(obs[0],observation_id='q',claim=Claim('device','pump','interlock','closed during startup'))
    rich=_evaluate_context((*obs,qualification),estimator=estimator_config())
    qualified={**chunks[1],'claim_ids':[cid,claim_id(qualification.claim)],'source':obs[0].source}
    result3=reconstruct_context(rich,[chunks[0],qualified,chunks[2]],token_budget=10000,strategy='coverage_support_query',chunk_relevance=dict.fromkeys('abc',1.))
    assert 'b' in result3['selected_chunk_ids']
    assert result3['claim_coverage']=={'covered':2,'total':2}


def test_better_representative_has_positive_marginal_gain_without_extra_dependency_penalty():
    obs,chunks=fixture();ev=_evaluate_context(obs,estimator=estimator_config())
    altered=replace(ev,claim_support=tuple(replace(c,supporting_sources=tuple(replace(s,independence=0.) for s in c.supporting_sources)) for c in ev.claim_support))
    assert _inferred_coverage_terms(ev,chunks)==_inferred_coverage_terms(altered,chunks)
    chunks[0]['raw_text']='x';chunks[1]['raw_text']='Longer original qualification '*10
    trace=[]
    result=reconstruct_context(ev,chunks,token_budget=10000,count_tokens=len,strategy='coverage_support_query',chunk_relevance={'a':.2,'b':1.,'c':0.},_selection_trace=trace)
    assert result['selection_order']==['a','b']
    second={c['chunk_id']:c for c in trace[1]['candidates']}
    mass=_inferred_coverage_terms(ev,chunks)['a'][claim_id(obs[0].claim)][1]
    assert second['b']['marginal_gain']==pytest.approx(mass*.8)
    assert result==reconstruct_context(ev,chunks,token_budget=10000,count_tokens=len,strategy='coverage_support_query',chunk_relevance={'a':.2,'b':1.,'c':0.})
    assert result['context']=='\n\n'.join('['+c['chunk_id']+']\n'+c['raw_text'] for c in chunks[:2])
    assert result['token_usage']==len(result['context'])<=10000


def test_grounding_preserves_qualified_facts_and_original_provenance():
    obs,_=fixture();old=replace(obs[0],metadata={'chunk_id':'chunk-a'})
    text='Before commit, write the checkpoint. The endpoint is available.'
    fact=dict(entity_namespace='transaction',entity='checkpoint',attribute='write_rule',value={'condition':'before commit','consequence':'write checkpoint'})
    async def provider(prompt):
        assert text in prompt and 'question' not in json.loads(prompt.split('Input JSON:\n')[1])
        return {'text':json.dumps(dict(decisions=[dict(entailed=False,evidence='')],missing=[dict(claim=fact,evidence='Before commit, write the checkpoint.')]))}
    got,audit=asyncio.run(_ground_chunk_observations([old],source_text=text,provider=provider))
    assert audit['status']=='grounded' and audit['rejected']==['a']
    assert len(got)==1 and got[0].claim.value==fact['value']
    assert replace(got[0],claim=old.claim,observation_id=old.observation_id,metadata=old.metadata)==old
    quote = 'Before commit, write the checkpoint.'
    assert got[0].metadata == {**old.metadata, 'source_span': {
        'start': 0, 'end': len(quote), 'text': quote}}
    assert audit['quotes'][got[0].observation_id] in text


@pytest.mark.parametrize('response',[
    {},dict(decisions=[],missing=[]),
    dict(decisions=[dict(entailed=True,evidence='Invented quote')],missing=[]),
    dict(decisions=[dict(entailed=True,evidence='Pressure is 250.')],missing=[]),
])
def test_invalid_grounding_abstains_without_dropping_evidence(response):
    obs,_=fixture()
    async def provider(prompt):return {'text':json.dumps(response)}
    got,audit=asyncio.run(_ground_chunk_observations([obs[0]],source_text='Pressure is 250.',provider=provider))
    assert got==(obs[0],) and audit['status']=='grounding_abstention'


def test_sdk_chunk_scores_weight_final_utility_without_experimental_flag():
    from omneum import open_stdio_client
    from benchmarks.context_selection.deployment import benchmark_deployment
    obs,chunks=fixture()
    async def run():
        with benchmark_deployment() as (config,server):
            async with open_stdio_client(config,server) as client:
                for strategy,options in [('coverage_support_query',{}),('coverage_support_density',dict(complementary_evidence=True,token_cost_exponent=1))]:
                    diag={}
                    result=await client.prepare_context(obs,chunks,estimator=estimator_config(),token_budget=10000,count_tokens=len,
                        strategy=strategy,chunk_relevance={'a':0.,'b':1.,'c':0.},relevance_score_type='normalized',candidate_discovery='all',query_diagnostics=diag,**options)
                    assert result['packed_chunk_ids']==['b']
                    assert diag['final_utility']=='inferred_support_mass_times_query_relevance'
                    first={c['chunk_id']:c for c in diag['utility_trace'][0]['candidates']}
                    assert first['a']['marginal_gain']==first['c']['marginal_gain']==0.
    asyncio.run(run())


def test_json_quoted_evidence_is_decoded_only_when_verbatim_in_source():
    from omneum.extraction import _source_quote
    source='He reported: pressure is 200.\r\n'
    assert _source_quote('"pressure is 200."',source)=='pressure is 200.'
    assert _source_quote('"pressure is 250."',source) is None
    assert _source_quote('pressure is 200.',source)=='pressure is 200.'
    assert _source_quote('pressure is  200.',source) is None


def test_nonlinear_complementary_mode_preserves_explicit_repeated_claim_credit():
    obs,chunks=fixture();ev=_evaluate_context(obs,estimator=estimator_config())
    def select(alpha):
        return reconstruct_context(ev,chunks,token_budget=10000,strategy='coverage_support_nonlinear',
            complementary_evidence=True,chunk_relevance=dict.fromkeys('abc',1.),covered_claim_credit=alpha)
    without=select(0.)
    with_credit=select(.25)
    assert len(without['selected_chunk_ids'])==1
    assert len(with_credit['selected_chunk_ids'])==2
    assert with_credit['selection_scores'][1]['marginal_gain']>0
    assert sum(s['marginal_gain'] for s in with_credit['selection_scores'])<=ev.claim_support[0].support
