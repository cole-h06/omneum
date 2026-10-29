import pytest

from omneum.context_selection import map_chunks, select_chunks


def select(chunks, support, budget, *, strategy='coverage_support_packed', count=len, penalty=0):
    return select_chunks(map_chunks(chunks, support), support, budget, strategy,
                         count_tokens=count, token_penalty=penalty)


def test_packed_ties_save_room_without_changing_default():
    chunks = [
        {'chunk_id': 'large', 'claim_ids': ['a'], 'raw_text': 'x'*60},
        {'chunk_id': 'small', 'claim_ids': ['a'], 'raw_text': 'x'},
        {'chunk_id': 'other', 'claim_ids': ['b'], 'raw_text': 'y'},
    ]
    support = {'a': 1.0, 'b': 0.5}
    original = select(chunks, support, 68, strategy='coverage_support')
    packed = select(chunks, support, 68)
    assert original['selected_chunk_ids'] == ['large']
    assert packed['selected_chunk_ids'] == ['small', 'other']
    assert packed['covered_support'] == 1.5
    assert packed['context'] == '[small]\nx\n\n[other]\ny'
    assert packed['candidate_scores'] == original['candidate_scores']
    assert packed['selection_scores'] == [
        {'chunk_id': 'small', 'score': 1.0, 'marginal_gain': 1.0},
        {'chunk_id': 'other', 'score': 0.5, 'marginal_gain': 0.5},
    ]


def test_rendering_order_and_remaining_ties_are_stable():
    chunks = [
        {'chunk_id': 'large', 'claim_ids': ['a'], 'raw_text': '  original\r\n'*4},
        {'chunk_id': 'small', 'claim_ids': ['b'], 'raw_text': '😀'},
    ]
    packed = select(chunks, {'a': 1.0, 'b': 1.0}, 1000)
    assert packed['selection_order'] == ['small', 'large']
    assert packed['selected_chunk_ids'] == ['large', 'small']
    assert packed['context'] == '[large]\n'+chunks[0]['raw_text']+'\n\n[small]\n😀'
    chunks[0]['raw_text'] = chunks[1]['raw_text'] = 'same'
    assert select(chunks, {'a': 1.0, 'b': 1.0}, 1000)['selection_order'] == ['large', 'small']
    assert packed['chunks'][0]['raw_text'] == '  original\r\n'*4


def test_exact_nonadditive_cost_and_positive_utility_stop():
    chunks = [
        {'chunk_id': 'a', 'claim_ids': ['a'], 'raw_text': 'x'},
        {'chunk_id': 'b', 'claim_ids': ['b'], 'raw_text': 'y'},
    ]
    def count(text):
        return len(text) - (3 if '\n\n' in text else 0)
    result = select(chunks, {'a': 2.0, 'b': 1.0}, 9, count=count, penalty=0.1)
    assert result['token_usage'] == count(result['context']) == 9
    assert [c['incremental_tokens'] for c in result['selection_scores']] == [5, 4]
    assert select(chunks, {'a': 0.5, 'b': 0.1}, 100, penalty=0.1)['chunks'] == []


def test_duplicate_coverage_does_not_fill_unused_budget():
    chunks = [
        {'chunk_id': 'a', 'claim_ids': ['a', 'a'], 'raw_text': 'same'},
        {'chunk_id': 'b', 'claim_ids': ['a'], 'raw_text': 'same'},
    ]
    result = select(chunks, {'a': 1.0}, 1000)
    assert result['selected_chunk_ids'] == ['a']
    assert result['claim_coverage'] == {'covered': 1, 'total': 1}


def test_larger_more_valuable_chunks_are_not_replaced_by_density():
    chunks = [
        {'chunk_id': 'large', 'claim_ids': ['a', 'b'], 'raw_text': 'x'*60},
        {'chunk_id': 'small', 'claim_ids': ['c'], 'raw_text': 'y'},
    ]
    assert select(chunks, {'a': 1.0, 'b': 1.0, 'c': 1.0}, 68)['selected_chunk_ids'] == ['large']


@pytest.mark.parametrize('budget', [0, 1, 8, 9, 14, 100])
def test_budget_enforcement(budget):
    chunks = [
        {'chunk_id': 'a', 'claim_ids': ['a'], 'raw_text': '😀\r\n'},
        {'chunk_id': 'b', 'claim_ids': ['b'], 'raw_text': 'original'},
    ]
    count = lambda text: len(text.encode())
    result = select(chunks, {'a': 1.0, 'b': 1.0}, budget, count=count)
    assert result['token_usage'] == count(result['context']) <= budget
    assert result == select(chunks, {'a': 1.0, 'b': 1.0}, budget, count=count)
