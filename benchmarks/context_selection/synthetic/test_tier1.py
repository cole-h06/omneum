import json
from pathlib import Path

from .loader import load_ground_truth
from .tier1_metrics import footprint, evidence_size, origins, measure, distribution, summarize


BASE = Path(__file__).parent


def candidate(name, text='A fact.', upstream=(), parents=()):
    return dict(source_id=name,text=text,source=dict(kind='web_document',identifier='https://example.org/'+name),
        provenance=dict(assertion_id=name,parent_assertion_ids=list(parents),
            upstream_sources=[dict(kind='web_document',identifier='https://example.org/'+s) for s in upstream]),
        claims=[dict(claim_id=name,observation_id=name,evidence=[dict(source_id=name,start=0,end=len(text),text=text)])])


def test_footprint_and_percentiles():
    assert footprint('Hello, world! λ_1\n')==5
    assert footprint('')==0
    assert distribution([1,2,3,4,5])==dict(n=5,p50=3,p95=4.8)


def test_evidence_deduplicates_overlapping_claim_spans():
    c = candidate('a','One fact. Another fact.')
    c['claims'].append(dict(claim_id='other',observation_id='other',evidence=c['claims'][0]['evidence']))
    assert evidence_size(c)==6


def test_independent_origins_keep_unselected_origin_in_denominator():
    rows=[candidate('a'),candidate('copy',upstream=['a']),candidate('b')]
    roots=origins(rows)
    assert roots['a']==roots['copy']=={('a',)}
    gold=set().union(*(roots[c['source_id']] for c in rows))
    assert len(roots['copy'])/len(gold)==.5


def test_parent_lineage_and_multi_origin_aggregation():
    rows=[candidate('a'),candidate('b'),candidate('summary',parents=['a','b'])]
    assert origins(rows)['summary']=={('a',),('b',)}


def test_citation_annotations_share_the_upstream_origin():
    rows=[candidate('a'),candidate('citation'),candidate('independent')]
    rows[1]['provenance']['cited_sources']=[rows[0]['source']]
    assert origins(rows)['citation']==origins(rows)['a']
    assert origins(rows)['independent']=={('independent',)}


def test_root_cycle_is_explicit_not_multiple_independent_sources():
    rows=[candidate('a',upstream=['b']),candidate('b',upstream=['a']),candidate('c')]
    roots=origins(rows)
    assert roots['a']==roots['b']=={('a','b')}
    assert roots['c']=={('c',)}


def test_real_case_preserves_metric_distinctions():
    directory=BASE/'canonical/cases/analytics_incomplete_lineage'
    case=json.loads((directory/'case.json').read_text())
    truth=load_ground_truth(directory/'ground_truth.json')
    c=case['candidates'][0]
    selected=['chunk-'+c['source_id']]
    result=measure(case,truth,selected,f"[{selected[0]}]\n{c['text']}")
    assert result['source_recall']==.25
    assert result['evidence_retention'] != result['source_recall']
    assert result['actual_context_tokens']==footprint(f"[{selected[0]}]\n{c['text']}")
    assert result['context_reduction']==(result['raw_context_tokens']-result['actual_context_tokens'])/result['raw_context_tokens']
    assert result['gold_claim_coverage'] is None
    assert 0 < result['supporting_passage_claim_coverage'] <= 1


def test_complete_and_empty_selection():
    directory=BASE/'canonical/cases/multi_agent_feedback_loop'
    case=json.loads((directory/'case.json').read_text());truth=load_ground_truth(directory/'ground_truth.json')
    all_ids=['chunk-'+c['source_id'] for c in case['candidates']]
    context='\n\n'.join(f"[{k}]\n{c['text']}" for k,c in zip(all_ids,case['candidates']))
    full=measure(case,truth,all_ids,context)
    empty=measure(case,truth,[],'')
    for key in ['evidence_retention','supporting_passage_claim_coverage','independent_evidence_coverage','source_recall']:
        assert full[key]==1 and empty[key]==0
    assert full['context_reduction']==0 and empty['context_reduction']==1


def test_quality_averages_cells_while_latency_uses_execution_samples():
    fields=['evidence_retention','actual_context_tokens','raw_context_tokens','context_reduction',
            'supporting_passage_claim_coverage','independent_evidence_coverage','source_precision',
            'source_recall','tokenizer_tokens','tokenizer_utilization','dependency_cluster_coverage',
            'budget_normalized_source_recall']
    cells=[dict(method='bge',**{k:v for k in fields}) for v in (.2,.8)]
    runs=[dict(method='bge',selection_ms=v) for v in (1,2,3,4,5)]
    result=summarize(cells,runs)['bge']
    assert result['evidence_retention']==.5 and result['cells']==2
    assert result['selection_ms']==dict(n=5,p50=3,p95=4.8)
    assert result['graph_ms']==dict(n=0,p50=None,p95=None)
    assert result['gold_claim_coverage'] is None
