"""Hand-computed production selection contracts; no transport or model calls."""
import pytest

from omneum import evaluate, reconstruct_context
from omneum.context_selection import claim_id, map_chunks, select_chunks


def two_claims():
    result = evaluate([
        {'url': 'https://fixture.example/policy', 'claim': {
            'entity_namespace': 'service', 'entity': 'fixture', 'attribute': name}, 'value': True}
        for name in ('audit', 'retention')])
    identifiers = [claim_id(item.claim) for item in result.claim_support]
    source = result.source_reliability[0].source
    return result, identifiers, source


@pytest.mark.parametrize('relevance', [0.0, 0.6, 1.0])
def test_answer_utility_multiplies_relevance_by_equal_weight_final_scores(relevance):
    evaluation, claims, source = two_claims()
    assert evaluation.source_reliability[0].reliability == 1.0
    assert [item.support for item in evaluation.claim_support] == [0.5, 0.5]
    trace = []
    result = reconstruct_context(evaluation, [dict(chunk_id='a', raw_text='A', claim_ids=claims, source=source)],
        strategy='coverage_answer', token_budget=5, count_tokens=len,
        chunk_relevance={'a': relevance}, _selection_trace=trace)
    # Per claim: q * (1 + R + s) / 3 = q * 2.5 / 3.
    # Two claims, divided by the five-character complete rendering [a]\nA.
    expected_gain = relevance * 5 / 3
    assert trace[0]['candidates'][0]['marginal_gain'] == pytest.approx(expected_gain)
    assert trace[0]['candidates'][0]['utility'] == pytest.approx(expected_gain / 5)
    assert result['context'] == ('[a]\nA' if relevance else '')
    assert result['token_usage'] == (5 if relevance else 0)


def test_duplicate_claims_receive_only_improvement_not_repeated_full_credit():
    evaluation, claims, source = two_claims()
    chunks = [dict(chunk_id='a', raw_text='A', claim_ids=claims, source=source),
              dict(chunk_id='b', raw_text='B', claim_ids=claims[:1], source=source),
              dict(chunk_id='copy', raw_text='A', claim_ids=claims, source=source)]
    trace = []
    result = reconstruct_context(evaluation, chunks, strategy='coverage_answer', token_budget=100,
        count_tokens=len, chunk_relevance={'a': .9, 'b': 1., 'copy': .9}, _selection_trace=trace)
    assert result['selection_order'] == ['a', 'b']
    second = {row['chunk_id']: row for row in trace[1]['candidates']}
    assert second['b']['marginal_gain'] == pytest.approx(5 / 6 - .75)
    assert second['copy']['marginal_gain'] == 0
    assert result['context'] == '[a]\nA\n\n[b]\nB'


def test_question_path_uses_local_passage_overlap_not_only_claim_labels():
    evaluation, claims, source = two_claims()
    chunks = [dict(chunk_id='a', raw_text='needle', claim_ids=claims[:1], source=source),
              dict(chunk_id='b', raw_text='unrelated', claim_ids=claims[1:], source=source)]
    from omneum.question_selection import lexical_claim_relevance
    assert set(lexical_claim_relevance('needle', {claim_id(c.claim): c.claim
                                                for c in evaluation.claim_support}).values()) == {0.0}
    result = reconstruct_context(evaluation, chunks, token_budget=100, question='needle')
    assert result['selected_chunk_ids'] == ['a']
    assert result['context'] == '[a]\nneedle'


@pytest.mark.parametrize('budget', [0, 4, 5, 6, 10, 11, 12])
def test_exact_rendered_budget_and_stable_ties(budget):
    chunks = [dict(chunk_id=name, raw_text=text, claim_ids=[name])
              for name, text in [('a', 'A'), ('b', 'B')]]
    mapping = map_chunks(chunks, {'a': .5, 'b': .5})
    def tokenizer(text):
        # Explicit boundary effect: the pair costs ten, not 5 + 5 + 2.
        return len(text) - (2 if '\n\n' in text else 0)
    result = select_chunks(mapping, {'a': .5, 'b': .5}, budget,
                           'coverage_support_density', count_tokens=tokenizer, token_cost_exponent=1)
    expected = [] if budget < 5 else ['a'] if budget < 10 else ['a', 'b']
    assert result['selection_order'] == expected
    assert result['token_usage'] == tokenizer(result['context']) <= budget
    assert result['context'] == '\n\n'.join(f'[{k}]\n{k.upper()}' for k in expected)
