import pytest

from omneum.context_selection import map_chunks, select_chunks


def select(chunks, support, budget=1000, **options):
    return select_chunks(map_chunks(chunks, support), support, budget, 'coverage_support_density',
                         count_tokens=lambda s: len(s.encode()), **options)


def test_zero_exponent_matches_packed_and_preserves_raw_text():
    chunks = [{'chunk_id':'a', 'raw_text':'😀\r\n', 'claim_ids':['x']},
              {'chunk_id':'b', 'raw_text':'long '*20, 'claim_ids':['x']},
              {'chunk_id':'c', 'raw_text':'qualification', 'claim_ids':['y']}]
    support = {'x':1.0, 'y':0.8}
    expected = select_chunks(map_chunks(chunks, support), support, 1000, 'coverage_support_packed',
                             count_tokens=lambda s: len(s.encode()))
    actual = select(chunks, support)
    for name in ('selected_chunk_ids','selection_order','candidate_scores','context','token_usage'):
        assert actual[name] == expected[name]
    assert actual['chunks'][0]['raw_text'] == chunks[0]['raw_text']


def test_density_checks_every_feasible_candidate_and_stops_at_nonpositive():
    chunks = [{'chunk_id':'large', 'raw_text':'x'*100, 'claim_ids':['x']},
              {'chunk_id':'small', 'raw_text':'y', 'claim_ids':['y']}]
    result = select(chunks, {'x':1.0,'y':0.8}, token_cost_exponent=1, token_penalty=0.001)
    assert result['selected_chunk_ids'] == ['small']
    assert result['selection_scores'][0]['regularized_utility'] > 0
    assert select(chunks, {'x':0.01,'y':0.01}, token_cost_exponent=1, token_penalty=1)['chunks'] == []
    claims = [f'essential-{i}' for i in range(20)]
    valuable_chunks = [{**chunks[0],'claim_ids':claims},chunks[1]]
    # Distinct claims can justify a large passage's whole-chunk cost.
    support = {claim:0.04 for claim in claims}
    valuable = select(valuable_chunks, {**support,'y':0.04}, 108, token_cost_exponent=1)
    assert valuable['selected_chunk_ids'] == ['large']


def test_complementary_sources_diminish_and_same_source_never_repeats():
    chunks = [{'chunk_id':k,'raw_text':'passage','claim_ids':['x']} for k in ('a','b','d','copy')]
    sources = {k:{'x':(s,w)} for k,s,w in [('a','source-a',1.0),('b','source-b',1.0),
                                          ('d','dependent-d',0.5),('copy','source-a',1.0)]}
    result = select(chunks, {'x':1.0}, complementary_sources=sources)
    assert result['selection_order'] == ['a','b','d']
    gains = [r['marginal_gain'] for r in result['selection_scores']]
    assert gains[0] > gains[1] > gains[2] > 0
    assert result['candidate_scores'] == {k:1.0 for k in ('a','b','d','copy')}


@pytest.mark.parametrize('budget',[0,1,15,30,80,1000])
def test_exact_budget_and_deterministic_reconstruction(budget):
    chunks = [{'chunk_id':'a','raw_text':'\r\n😀','claim_ids':['x','y']},
              {'chunk_id':'b','raw_text':'qualification','claim_ids':['y']},
              {'chunk_id':'c','raw_text':'noise','claim_ids':['z']}]
    options = {'token_cost_exponent':0.5, 'token_penalty':0.0001}
    result = select(chunks, {'x':0.5,'y':0.5,'z':0.1}, budget, **options)
    assert result['token_usage'] == len(result['context'].encode()) <= budget
    assert result == select(chunks, {'x':0.5,'y':0.5,'z':0.1}, budget, **options)


@pytest.mark.parametrize('exponent',[-1,True,float('inf'),float('nan')])
def test_invalid_exponents(exponent):
    with pytest.raises(ValueError):
        select([], {}, token_cost_exponent=exponent)


def test_large_finite_exponent_does_not_overflow():
    chunks = [{'chunk_id':'a','raw_text':'passage','claim_ids':['x']}]
    assert select(chunks, {'x':1.0}, token_cost_exponent=1e308)['chunks'] == []


def test_dependent_replication_does_not_increase_total_support_mass():
    gains = []
    for size in (1,2,4):
        chunks = [{'chunk_id':str(i),'raw_text':'same','claim_ids':['x']} for i in range(size)]
        weights = {str(i):{'x':(str(i),1/size)} for i in range(size)}
        result = select(chunks, {'x':1.0}, complementary_sources=weights)
        gains.append(sum(c['marginal_gain'] for c in result['selection_scores']))
    assert gains == [1.0,1.0,1.0]
