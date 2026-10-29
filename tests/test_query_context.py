import asyncio
from copy import deepcopy
from dataclasses import asdict
import json

import pytest

from omneum import Claim, LocalPersistenceConfig, OmneumClient, Observation, Source, open_stdio_client
from omneum.context_selection import claim_id, map_chunks
from omneum.client import _snapshot_observations
from omneum.mcp import ClientSession
from omneum.query_context import expand_claims, plan_context, rank_claims
from omneum.storage import SQLiteStorage
from benchmarks.context_selection.config import estimator_config
from benchmarks.context_selection.deployment import benchmark_deployment
from test_client_evaluation import make_observation


class Encoder:
    def encode(self, texts, **kwargs):
        return [[1.0, 0.0] if text in ('PRIVATE user query', 'anchor') else [0.0, 1.0] for text in texts]


def inputs():
    anchor = Claim('service', 'account', 'retention', '30 days')
    exception = Claim('service', 'account', 'exception', 'legal hold')
    noise = Claim('service', 'other', 'quota', 8)
    a, b, d = (Source('web_document', f'https://{name}.example') for name in ('a','b','d'))
    observations = (
        make_observation('noise', b, noise),
        make_observation('anchor-a', a, anchor, parent_observation_ids=('noise',)),
        make_observation('exception', a, exception),
        make_observation('anchor-d', d, anchor, parent_observation_ids=('noise',)),
    )
    chunks = [
        {'chunk_id':'a', 'raw_text':'PRIVATE original retention. Legal hold exception.\r\n😀',
         'claim_ids':[claim_id(anchor),claim_id(exception)],'source':a},
        {'chunk_id':'d', 'raw_text':'PRIVATE copied retention.', 'claim_ids':[claim_id(anchor)],'source':d},
        {'chunk_id':'b', 'raw_text':'PRIVATE unrelated quota.', 'claim_ids':[claim_id(noise)],'source':b},
    ]
    texts={claim_id(anchor):'anchor',claim_id(exception):'qualification',claim_id(noise):'noise'}
    return observations,chunks,texts


def plan(observations,chunks,texts,**kwargs):
    return plan_context(observations,chunks,estimator=estimator_config(),user_query=kwargs.pop('query','PRIVATE user query'),
        anchor_count=kwargs.pop('anchors',1),expansion_depth=kwargs.pop('depth',1),
        claim_texts=texts,semantic_model=kwargs.pop('model',Encoder()),**kwargs)


def test_anchor_qualification_and_dependency_context():
    observations,chunks,texts=inputs()
    result=plan(observations,chunks,texts)
    assert result['diagnostics']['anchor_claim_ids']==[chunks[1]['claim_ids'][0]]
    assert result['diagnostics']['relevance_scores'][chunks[0]['claim_ids'][1]]==0
    assert [c['chunk_id'] for c in result['chunks']]==['a','d']
    assert {o.observation_id for o in result['observations']}=={'anchor-a','anchor-d','exception'}
    assert result['observations'][0].parent_observation_ids==('noise',)
    assert any(p.dependency==1.0 for p in result['pairs'])
    assert chunks[0]['claim_ids'][1] in result['diagnostics']['expanded_claim_ids']


def test_hops_cycles_disconnected_claims_and_determinism():
    observations,chunks,texts=inputs()
    extra=Claim('service','account','quota',9)
    observations=(*observations,make_observation('extra',observations[1].source,extra))
    chunks=[*chunks,{'chunk_id':'extra','raw_text':'Extra source assertion.','claim_ids':[claim_id(extra)]}]
    ids={claim_id(o.claim) for o in observations}
    mapping=map_chunks(chunks,ids)
    anchor=chunks[1]['claim_ids'][0]
    one=expand_claims(observations,mapping,[anchor,anchor],1)
    two=expand_claims(observations,mapping,[anchor],2)
    assert 'extra' not in one['chunk_ids'] and 'extra' in two['chunk_ids']
    assert 'b' not in two['chunk_ids']
    assert two==expand_claims(observations,mapping,[anchor,anchor],2)
    assert len(two['chunk_ids'])==len(set(two['chunk_ids']))
    assert expand_claims(observations,mapping,[],2)['chunk_ids']==[]
    with pytest.raises(ValueError,match='unknown anchor'):
        expand_claims(observations,mapping,['unknown'],1)


def test_empty_missing_and_unavailable_semantics_fall_back():
    observations,chunks,texts=inputs()
    class Unavailable:
        def encode(self,*args,**kwargs):
            raise OSError('private provider details must not be returned')
    for options,expected in [({'query':' '},'empty_query'),({'model':Unavailable()},'semantic_model_unavailable')]:
        result=plan(observations,chunks,texts,**options)
        assert [asdict(o) for o in result['observations']]==[asdict(o) for o in _snapshot_observations(observations)]
        assert result['chunks']==chunks
        assert result['diagnostics']['fallback_reason']==expected
        assert 'private provider' not in json.dumps(result['diagnostics'])
    result=plan(observations,chunks,{next(iter(texts)):'anchor'})
    assert result['diagnostics']['fallback_reason']=='missing_claim_text'
    assert result['diagnostics']['relevance_scores']=={}
    assert plan(observations,[],texts)['diagnostics']['fallback_reason']=='empty_chunks'


def test_raw_cosine_scores_and_bad_vectors():
    class Model:
        def encode(self,texts,**kwargs):
            return [[1,0],[2,0],[-3,0]]
    assert rank_claims('query',{'a':'one','b':'two'},Model())=={'a':1.0,'b':-1.0}
    class Invalid:
        def encode(self,texts,**kwargs):
            return [[float('nan')]]*len(texts)
    observations,chunks,texts=inputs()
    with pytest.raises(ValueError,match='invalid vectors'):
        plan(observations,chunks,texts,model=Invalid())


@pytest.mark.parametrize('options',[{'anchors':0},{'anchors':True},{'depth':0},{'depth':3}])
def test_invalid_bounds(options):
    observations,chunks,texts=inputs()
    with pytest.raises(ValueError):plan(observations,chunks,texts,**options)


def test_real_sdk_local_full_normalization_persistence_and_wire(tmp_path,monkeypatch,capsys):
    observations,chunks,texts=inputs()
    original=deepcopy(chunks)
    calls=[]
    evaluations=[]
    old_call=ClientSession.call_tool
    old_eval=OmneumClient._evaluate_context
    async def capture(self,name,arguments=None,*args,**kwargs):
        if name=='evaluate_context':calls.append(deepcopy(arguments))
        return await old_call(self,name,arguments,*args,**kwargs)
    async def evaluate(self,*args,**kwargs):
        value=await old_eval(self,*args,**kwargs)
        evaluations.append(value)
        return value
    monkeypatch.setattr(ClientSession,'call_tool',capture)
    monkeypatch.setattr(OmneumClient,'_evaluate_context',evaluate)
    async def run():
        storage=SQLiteStorage(tmp_path/'graph.db')
        with benchmark_deployment() as (config,server):
            async with open_stdio_client(config,server,local_persistence=LocalPersistenceConfig(storage)) as client:
                baseline=await client.prepare_context(observations,chunks,estimator=estimator_config(),token_budget=2000,count_tokens=len)
                diag={}
                local=await client.prepare_context(observations,chunks,estimator=estimator_config(),token_budget=2000,count_tokens=len,
                    user_query='PRIVATE user query',anchor_count=1,claim_texts=texts,semantic_model=Encoder(),query_diagnostics=diag)
                full=await client.prepare_context(observations,chunks,estimator=estimator_config(),token_budget=2000,count_tokens=len,
                    user_query='PRIVATE user query',anchor_count=1,claim_texts=texts,semantic_model=Encoder(),query_evaluation='full')
                fallback=await client.prepare_context(observations,chunks,estimator=estimator_config(),token_budget=2000,count_tokens=len,user_query=' ')
                complementary=await client.prepare_context(observations,chunks,estimator=estimator_config(),
                    token_budget=2000,count_tokens=len,user_query='PRIVATE user query',anchor_count=1,
                    claim_texts=texts,semantic_model=Encoder(),strategy='coverage_support_density',
                    complementary_evidence=True,token_cost_exponent=1)
                assert complementary['evaluation']==local['evaluation']
                assert complementary['context'].count('Legal hold exception.')==1
                assert complementary['selection']['selected_tokens']<=2000
                assert fallback==baseline
                assert len(local['evaluation']['source_reliability'])==2
                assert len(full['evaluation']['source_reliability'])==3
                assert full['evaluation']==baseline['evaluation']
                assert local['evaluation']['claim_support']!=baseline['evaluation']['claim_support']
                assert 'PRIVATE unrelated' not in local['context']
                assert 'Legal hold exception.' in local['context']
                assert local['selection']['input_tokens']==baseline['selection']['input_tokens']
                assert diag['expanded_claims']==2 and diag['expanded_edges']==3
                full_pairs={frozenset((p.source_a.identifier,p.source_b.identifier)):p.dependency for p in evaluations[0].pairwise_dependencies}
                assert all(p.dependency==full_pairs[frozenset((p.source_a.identifier,p.source_b.identifier))] for p in evaluations[1].pairwise_dependencies)
                for result in (baseline,local,full):json.dumps(result,allow_nan=False)
        import sqlite3
        with sqlite3.connect(storage.path) as db:
            assert db.execute('SELECT count(*) FROM evaluation_runs').fetchone()[0]==5
            assert db.execute('SELECT count(*) FROM execution_history').fetchone()[0]==5
            assert not db.execute('PRAGMA foreign_key_check').fetchall()
    asyncio.run(run())
    assert len(calls)==5
    wire=json.dumps(calls)
    assert 'PRIVATE' not in wire and 'Legal hold exception' not in wire
    assert chunks==original
    output=capsys.readouterr()
    assert output.out==output.err==''


def test_conflicting_source_owners_rejected_before_localization():
    from dataclasses import replace
    from omneum.dependency import InformationGraphError
    observations,chunks,texts = inputs()
    source = replace(observations[1].source,owner_id='different-owner')
    changed = (*observations[:2],replace(observations[2],source=source),*observations[3:])
    with pytest.raises(InformationGraphError,match='conflicting owners'):
        plan(changed,chunks,texts)


def test_high_degree_source_is_bounded_to_two_hops():
    observations,chunks,texts = inputs()
    source = observations[1].source
    for index in range(40):
        claim = Claim('service','account',f'unrelated_{index}',index)
        observations = (*observations,make_observation(f'other-{index}',source,claim))
        chunks.append({'chunk_id':f'other-{index}','claim_ids':[claim_id(claim)],'raw_text':'Unrelated assertion.'})
    mapping = map_chunks(chunks,{claim_id(o.claim) for o in observations})
    anchor = chunks[1]['claim_ids'][0]
    one = expand_claims(observations,mapping,[anchor],1)
    two = expand_claims(observations,mapping,[anchor],2)
    assert one['chunk_ids'] == ['a','d']
    assert len(two['chunk_ids']) == 42
    assert 'b' not in two['chunk_ids']
    assert len(set(two['claim_ids'])) == 42
    assert len(set(two['source_keys'])) == 2


def test_threshold_boundary_maximum_and_exclusions():
    observations, chunks, texts = inputs()
    anchor, exception = chunks[0]['claim_ids']
    noise = chunks[2]['claim_ids'][0]
    chunks = [*chunks, {'chunk_id': 'exception-only', 'raw_text': 'Legal hold.',
                       'claim_ids': [exception], 'source': observations[1].source}]
    scores = {anchor: 0.8, exception: 0.149, noise: 0.15}
    result = plan_context(
        observations, chunks, estimator=estimator_config(), user_query='',
        anchor_count=1, expansion_depth=1, claim_texts=None,
        claim_relevance=scores, query_anchoring=False, relevance_threshold=0.15,
    )
    diag = result['diagnostics']
    assert diag['eligible_chunk_ids'] == ['a', 'd', 'b']
    assert diag['chunk_relevance']['a'] == 0.8
    assert diag['chunk_relevance']['b'] == 0.15
    assert diag['excluded_chunks'] == [{'chunk_id': 'exception-only', 'relevance': 0.149}]
    assert diag['anchor_claim_ids'] == []
    assert result['chunks'][0]['raw_text'] == chunks[0]['raw_text']
    scores[exception] = 0.0
    scores[noise] = 0.0
    zero = plan_context(
        observations, chunks, estimator=estimator_config(), user_query='',
        anchor_count=1, expansion_depth=1, claim_texts=None,
        claim_relevance=scores, query_anchoring=False, relevance_threshold=0.15,
    )
    assert zero['diagnostics']['eligible_chunk_ids'] == ['a', 'd']
    all_chunks = plan_context(
        observations, chunks, estimator=estimator_config(), user_query='',
        anchor_count=1, expansion_depth=1, claim_texts=None,
        claim_relevance=scores, query_anchoring=False,
    )
    assert all_chunks['chunks'] == chunks
    assert all_chunks['diagnostics']['excluded_chunks'] == []


@pytest.mark.parametrize('threshold', [-0.01, 1.01, True, float('nan'), float('inf'), '0.15'])
def test_invalid_relevance_threshold(threshold):
    observations, chunks, texts = inputs()
    with pytest.raises(ValueError, match='threshold'):
        plan_context(observations, chunks, estimator=estimator_config(), user_query='q',
                     anchor_count=1, expansion_depth=1, claim_texts=texts,
                     semantic_model=Encoder(), relevance_threshold=threshold)


@pytest.mark.parametrize('scores', [{}, {'unknown': 0.5}, None])
def test_threshold_missing_relevance_is_explicit(scores):
    observations, chunks, _ = inputs()
    with pytest.raises(ValueError, match='relevance|semantics'):
        plan_context(observations, chunks, estimator=estimator_config(), user_query='',
                     anchor_count=1, expansion_depth=1, claim_texts=None,
                     claim_relevance=scores, relevance_threshold=0.15)


def test_gates_preserve_full_graph_complementary_utility_and_mcp(tmp_path, monkeypatch, capsys):
    observations, chunks, texts = inputs()
    anchor, exception = chunks[0]['claim_ids']
    scores = {anchor: 0.8, exception: 0.01, chunks[2]['claim_ids'][0]: 0.15}
    calls, evaluations = [], []
    old_call = ClientSession.call_tool
    old_evaluate = OmneumClient._evaluate_context
    async def capture(self, name, arguments=None, *args, **kwargs):
        if name == 'evaluate_context':
            calls.append(deepcopy(arguments))
        return await old_call(self, name, arguments, *args, **kwargs)
    async def evaluate(self, *args, **kwargs):
        result = await old_evaluate(self, *args, **kwargs)
        evaluations.append(result)
        return result
    monkeypatch.setattr(ClientSession, 'call_tool', capture)
    monkeypatch.setattr(OmneumClient, '_evaluate_context', evaluate)
    async def run():
        storage = SQLiteStorage(tmp_path / 'omneum.db')
        with benchmark_deployment() as (config, server):
            async with open_stdio_client(config, server, local_persistence=LocalPersistenceConfig(storage)) as client:
                options = dict(estimator=estimator_config(), token_budget=2000,
                               count_tokens=lambda text: len(text.encode()), strategy='coverage_support_density',
                               token_cost_exponent=1.0, complementary_evidence=True)
                control = await client.prepare_context(observations, chunks, **options)
                outputs, diagnostics = [], []
                for settings in ({'query_anchoring': False},
                                 {'query_anchoring': False, 'relevance_threshold': 0.15},
                                 {'anchor_count': 1, 'expansion_depth': 2}):
                    diag = {}
                    result = await client.prepare_context(
                        observations, chunks, **options, user_query='PRIVATE query',
                        claim_relevance=scores, query_evaluation='full', query_diagnostics=diag, **settings,
                    )
                    assert result['evaluation'] == control['evaluation']
                    assert result['selection']['selected_tokens'] == len(result['context'].encode()) <= 2000
                    assert result['selection']['input_tokens'] == control['selection']['input_tokens']
                    assert 'Legal hold exception.' in result['context']
                    assert 'telemetry' not in result
                    json.dumps(result, allow_nan=False)
                    outputs.append(result)
                    diagnostics.append(diag)
                assert outputs[0] == outputs[1] == control
                assert diagnostics[0]['selection_scores'] == diagnostics[1]['selection_scores']
                assert diagnostics[2]['expanded_chunk_ids'] == ['a', 'd']
                assert diagnostics[2]['excluded_chunks'] == [{'chunk_id': 'b', 'relevance': 0.15}]
                # Complete candidate sets reproduce utility even when every
                # claim is also an anchor; graph traversal only changes eligibility.
                all_anchors = await client.prepare_context(
                    observations, chunks, **options, claim_relevance=scores,
                    query_evaluation='full', anchor_count=len(scores), expansion_depth=2,
                )
                assert all_anchors == control
        assert len(evaluations) == 5
        first = evaluations[0]
        for result in evaluations[1:]:
            assert result.source_reliability == first.source_reliability
            assert result.claim_support == first.claim_support
            assert result.pairwise_dependencies == first.pairwise_dependencies
            assert result.convergence == first.convergence
        weights = [s.independence for c in first.claim_support for s in c.supporting_sources]
        assert any(0 < weight < 1 for weight in weights)
    asyncio.run(run())
    assert len(calls) == 5 and all(call == calls[0] for call in calls)
    assert 'PRIVATE' not in json.dumps(calls)
    assert capsys.readouterr() == ('', '')


def test_source_expansion_recovers_a_separate_low_relevance_exception():
    observations, chunks, _ = inputs()
    anchor, exception = chunks[0]['claim_ids']
    noise = chunks[2]['claim_ids'][0]
    chunks[0] = {**chunks[0], 'raw_text': 'Retention is 30 days.', 'claim_ids': [anchor]}
    chunks.append({'chunk_id': 'exception', 'raw_text': 'Legal holds suspend expiration.',
                   'claim_ids': [exception], 'source': observations[1].source})
    options = dict(estimator=estimator_config(), user_query='', anchor_count=1,
                   claim_texts=None, claim_relevance={anchor: 0.8, exception: 0.01, noise: 0.0})
    threshold = plan_context(observations, chunks, **options, expansion_depth=2,
                             query_anchoring=False, relevance_threshold=0.15)
    one = plan_context(observations, chunks, **options, expansion_depth=1)
    two = plan_context(observations, chunks, **options, expansion_depth=2)
    assert threshold['diagnostics']['eligible_chunk_ids'] == ['a', 'd']
    assert one['diagnostics']['eligible_chunk_ids'] == ['a', 'd']
    assert two['diagnostics']['eligible_chunk_ids'] == ['a', 'd', 'exception']
    assert two['chunks'][-1]['raw_text'] == chunks[-1]['raw_text']
    assert two['diagnostics']['anchor_claim_ids'] == [anchor]
    assert 'b' not in two['diagnostics']['eligible_chunk_ids']
