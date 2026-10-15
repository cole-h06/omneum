"""Conflict selection regressions: no providers, reranking, or daemon calls."""
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from benchmarks.context_evaluation.omneum_rag import select_reliable_context
from benchmarks.context_evaluation.config import estimator_config
from .loader import load_case, build_observations
from benchmarks.context_evaluation.omneum_rag import map_observations
from omneum.dependency import estimate_dependencies, _canonical_claim, _canonical_source
from omneum.engine_graph import AssertionTriple, SourcePair, build_graph
from omneum.inference import infer
from omneum.serialization import serialize_attribute, serialize_claim

BASE = Path(__file__).resolve().parent


def context(rows, claims, dependencies=()):
    mapped = [{'retrieved': {'source':name, 'reranker_score':relevance},
               'observation':NS(source=name)} for name,relevance,quality in rows]
    evaluation = NS(
        source_reliability=[NS(source=name,reliability=quality) for name,relevance,quality in rows],
        claim_support=[NS(claim=NS(entity_namespace='test',entity='entity',attribute=attribute,value=value),
            supporting_sources=[NS(source=name) for name in sources],
            is_attribute_max_support=index==0) for index,(attribute,value,sources) in enumerate(claims)],
        pairwise_dependencies=[NS(source_a=a,source_b=b,dependency=d) for a,b,d in dependencies],
        dependency_cluster_threshold=.3,
    )
    return mapped,evaluation


def choose(mapped,evaluation,budget):
    return [d['retrieved']['source'] for d in select_reliable_context(mapped,evaluation,top_n=budget)]


def reconstruct(case, shortlist, estimator):
    observations, source_ids = build_observations(case)
    eligible = {d['source'] for d in shortlist}
    included = set(eligible)
    by_id = {o.observation_id: o for o in observations}
    by_source = {_canonical_source(o.source): o for o in observations}
    while True:
        before = set(included)
        for o in observations:
            if source_ids[o.source] not in included:
                continue
            for ref in (*o.upstream_sources, *o.cited_sources):
                parent = by_source.get(_canonical_source(ref))
                if parent:
                    included.add(source_ids[parent.source])
            for parent_id in o.parent_observation_ids:
                included.add(source_ids[by_id[parent_id].source])
        if included == before:
            break
    values = tuple(o for o in observations if source_ids[o.source] in included)
    sources = tuple(o.source for o in values)
    pairs, _ = estimate_dependencies(sources, values, estimator)
    triples, claims = [], {}
    for o in values:
        canonical = _canonical_claim(o.claim)
        attr = serialize_attribute(*canonical[:3]).hex()
        claim_id = serialize_claim(*canonical).hex()
        claims[claim_id] = o.claim
        triples.append(AssertionTriple(source_ids[o.source], attr, claim_id))
    engine_pairs = []
    for p in pairs:
        a = source_ids[by_source[(p.source_a.kind,p.source_a.identifier)].source]
        b = source_ids[by_source[(p.source_b.kind,p.source_b.identifier)].source]
        a, b = sorted((a,b))
        engine_pairs.append(SourcePair(a,b,p.dependency,p.weighted_signal_coverage))
    graph = build_graph(triples, engine_pairs)
    result = infer(graph)
    source_objects = {source_ids[o.source]: o.source for o in values}
    evaluation = NS(
        source_reliability=[NS(source=source_objects[s.source_id], reliability=s.reliability) for s in result.source_reliability],
        claim_support=[NS(claim=claims[c.claim_id], support=c.support, is_attribute_max_support=c.is_attribute_max_support,
            supporting_sources=[NS(source=source_objects[s.source_id], contribution=s.contribution) for s in c.supporting_sources]) for c in result.claim_support],
        pairwise_dependencies=[NS(source_a=source_objects[a], source_b=source_objects[b], dependency=p.dependency) for (a,b),p in graph.source_pairs.items()],
        dependency_cluster_threshold=estimator.dependency_cluster_threshold,
    )
    return map_observations(shortlist, observations, source_ids), evaluation

def test_census_selection():
    case = load_case(BASE/'cases/research_independent_false_consensus/case.json')
    text = {c.source_id:c.text for c in case.candidates}
    # Recorded BGE shortlist, kept here so the test needs no historical run files.
    shortlist = [{'source':name, 'text':text[name], 'reranker_score':score} for name,score in (
        ('dataset', .9885224103927612), ('analysis', .9757828712463379),
        ('report', .9729679822921753), ('publication', .7544775009155273),
        ('web_page', .6921607255935669), ('news_article', .5554463267326355),
    )]
    mapped,result = reconstruct(case,shortlist,estimator_config())
    assert choose(mapped,result,3) == ['analysis','report','dataset']


def test_relevant_dissent():
    mapped,result=context([('estimate1',.9,.25),('estimate2',.8,.25),('estimate3',.7,.25),('measurement',.99,.05)],
        [('count',240,['estimate1','estimate2','estimate3']),('count',216,['measurement'])])
    assert choose(mapped,result,2)==['estimate1','measurement']
    assert choose(mapped,result,3)==['estimate1','estimate2','measurement']


@pytest.mark.parametrize('budget,expected',[(0,[]),(1,['a']),(2,['a','b']),(3,['a','b','c'])])
def test_budget_tiebreaks(budget,expected):
    mapped,result=context([('a',.9,.5),('a_copy',.89,.5),('b',.8,.5),('c',.8,.5)],
        [('count',1,['a','a_copy']),('count',2,['b']),('count',3,['c'])])
    assert choose(mapped,result,budget)==expected


def test_nonconflicting_selection():
    mapped,result=context([('a',.9,.1),('b',.8,.5),('c',.7,.5)],
        [('count',1,['a','b','c'])],[('b','c',1.)])
    assert choose(mapped,result,2)==['b','c']


def test_independent_corroboration():
    mapped,result=context([('a',.99,.5),('copy',.98,.5),('independent',.7,.5),('dissent',.9,.1)],
        [('count',1,['a','copy','independent']),('count',2,['dissent'])],[('a','copy',1.)])
    assert choose(mapped,result,3)==['a','independent','dissent']
    # Copies can fill spare capacity; the runner's fixed context budget is honored.
    assert choose(mapped,result,4)==['a','copy','independent','dissent']


def test_distinct_attributes_are_not_competing_claims():
    mapped,result=context([('a',.99,.5),('b',.98,.5),('c',.1,.5)],
        [('count',1,['a','b']),('date',2,['c'])])
    assert choose(mapped,result,2)==['a','b']


def test_zero_relevance_does_not_reserve_a_conflict_slot():
    mapped,result=context([('a',.9,.5),('b',.8,.5),('irrelevant',0.,.9)],
        [('count',1,['a','b']),('count',2,['irrelevant'])])
    assert choose(mapped,result,2)==['a','b']


def test_duplicate_source_selected_only_once():
    mapped,result=context([('a',.9,.5),('b',.8,.5)], [('count',1,['a']),('count',2,['b'])])
    mapped.append(mapped[0])
    assert choose(mapped,result,5)==['a','b']


def test_single_slot_keeps_highest_score_across_attributes():
    mapped,result=context([('unrelated_attribute',.99,.9),('a',.9,.5),('b',.8,.5)],
        [('date',3,['unrelated_attribute']),('count',1,['a']),('count',2,['b'])])
    assert choose(mapped,result,1)==['unrelated_attribute']
