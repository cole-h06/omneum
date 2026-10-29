"""Competing properties widen eligibility without opening new neighborhoods."""
from copy import deepcopy

import pytest

from omneum import Claim, Source
from omneum.context_selection import claim_id, map_chunks
from omneum.query_context import discover_chunks, expand_claims
from test_client_evaluation import make_observation


def discover(observations, chunks, *, depth=1, enabled=True):
    mapping = map_chunks(chunks, {claim_id(o.claim) for o in observations})
    scores = {c['chunk_id']: float(i == 0) for i, c in enumerate(chunks)}
    return discover_chunks(observations, mapping, scores, 'normalized', 'expanded', 1,
                           depth, conflict_aware=enabled)


@pytest.mark.parametrize('other, expected', [
    (Claim('release', 'Build 118 production current', 'approval status', 'blocked'), ['0', '1']),
    (Claim('release', ' BUILD 118 PRODUCTION CURRENT ', ' Approval   Status ', 'blocked'), ['0', '1']),
    (Claim('release', 'Build 118 production current', 'approval status', 'approved'), ['0', '1']),
    (Claim('release', 'Build 118 production current', 'deployment status', 'blocked'), ['0']),
    (Claim('release', 'Build 118 CI current', 'approval status', 'blocked'), ['0']),
    (Claim('release', 'Build 118 production historical', 'approval status', 'blocked'), ['0']),
    (Claim('other', 'Build 118 production current', 'approval status', 'blocked'), ['0']),
    (Claim('release', 'Build 118 production current under load', 'approval status', 'blocked'), ['0']),
    (Claim('release', 'Build 118 production current', 'approval status p95 milliseconds', 50), ['0']),
    (Claim('release', 'Build 118 production current', 'approval action', 'block'), ['0']),
])
def test_complete_canonical_property_identity(other, expected):
    anchor = Claim('release', 'Build 118 production current', 'approval status', 'approved')
    observations = tuple(make_observation(str(i), Source('web_document', f'https://s{i}.example'), c)
                         for i, c in enumerate((anchor, other)))
    chunks = [dict(chunk_id=str(i), raw_text=f'Original {i}\r\n', claim_ids=[claim_id(c)], source=o.source)
              for i, (c, o) in enumerate(zip((anchor, other), observations))]
    before = deepcopy((observations, chunks))
    result = discover(observations, chunks)
    assert result['eligible_chunk_ids'] == expected
    assert [c['chunk_id'] for c in result['excluded_chunks']] == ([] if len(expected) == 2 else ['1'])
    assert (observations, chunks) == before
    baseline = discover(observations, chunks, enabled=False)
    assert baseline['eligible_chunk_ids'] == (['0', '1'] if claim_id(anchor) == claim_id(other) else ['0'])


@pytest.mark.parametrize('value', [
    {'condition': 'production', 'status': 'approved'},
    {'condition': 'CI', 'status': 'blocked'},
    {'time': 'historical', 'status': 'blocked'},
    {'measurement': 'p95', 'value': 20},
    {'measurement': 'mean', 'value': 20},
    ['approved', 'conditional'],
])
def test_structured_conditions_keep_exact_claim_identity(value):
    claims = [Claim('release', 'build', 'status', {'condition': 'production', 'status': 'approved'}),
              Claim('release', 'build', 'status', value)]
    observations = tuple(make_observation(str(i), Source('web_document', f'https://s{i}.example'), c)
                         for i, c in enumerate(claims))
    chunks = [dict(chunk_id=str(i), raw_text=str(i), claim_ids=[claim_id(c)]) for i, c in enumerate(claims)]
    assert discover(observations, chunks)['eligible_chunk_ids'] == (
        ['0', '1'] if claim_id(claims[0]) == claim_id(claims[1]) else ['0'])


@pytest.mark.parametrize('depth', [1, 2])
def test_terminal_conflict_closure_keeps_chunks_whole_without_recursing(depth):
    a, b = (Source('web_document', f'https://{name}.example') for name in ('a', 'b'))
    approved, blocked = (Claim('release', 'build', 'status', v) for v in ('approved', 'blocked'))
    colocated = Claim('release', 'build', 'test', 'failed')
    colocated_competitor = Claim('release', 'build', 'test', 'passed')
    ordinary = Claim('release', 'build', 'ordinary', 'one')
    ordinary_competitor = Claim('release', 'build', 'ordinary', 'two')
    unrelated = Claim('release', 'build', 'other', 'noise')
    specs = [(approved, a), (blocked, b), (colocated, b), (unrelated, b),
             (ordinary, a), (ordinary_competitor, b), (colocated_competitor, b)]
    observations = tuple(make_observation(str(i), s, c) for i, (c, s) in enumerate(specs))
    chunks = [dict(chunk_id=k, raw_text=k, claim_ids=[claim_id(c) for c in cs]) for k, cs in [
        ('anchor', [approved]), ('competing', [blocked, colocated]), ('copy', [blocked]),
        ('noise', [unrelated]), ('ordinary', [ordinary]), ('ordinary-conflict', [ordinary_competitor]),
        ('colocated-conflict', [colocated_competitor])]]
    result = discover(observations, chunks, depth=depth)
    expected = ['anchor', 'competing', 'copy']
    if depth == 2:
        expected += ['ordinary', 'ordinary-conflict']
    assert result['eligible_chunk_ids'] == expected
    assert len(expected) == len(set(result['eligible_chunk_ids']))
    assert claim_id(colocated) in result['expanded_claim_ids']
    assert claim_id(unrelated) not in result['expanded_claim_ids']
    repeated = discover(tuple(reversed(observations)), chunks, depth=depth)
    for key in ('eligible_chunk_ids', 'expanded_claim_ids', 'excluded_chunks', 'traversed_edges'):
        assert repeated[key] == result[key]
    mapping = map_chunks(chunks, {claim_id(o.claim) for o in observations})
    assert expand_claims(observations, mapping, [], depth, conflict_aware=True)['chunk_ids'] == []


def test_sdk_conflict_eligibility_preserves_full_inference_and_budget(monkeypatch):
    import asyncio
    import omneum.query_context as query_context
    from omneum import OmneumClient, open_stdio_client
    from benchmarks.context_selection.config import estimator_config
    from benchmarks.context_selection.deployment import benchmark_deployment

    claims = [Claim('release', 'build', 'status', v) for v in ('approved', 'blocked')]
    observations = tuple(make_observation(str(i), Source('web_document', f'https://s{i}.example'), c)
                         for i, c in enumerate(claims))
    chunks = [dict(chunk_id=str(i), raw_text=f'Original {i}\r\n', claim_ids=[claim_id(c)], source=o.source)
              for i, (c, o) in enumerate(zip(claims, observations))]
    original = deepcopy((observations, chunks))
    discovery = query_context.discover_chunks
    evaluate = OmneumClient._evaluate_context
    inputs = []

    async def capture(self, values, **options):
        inputs.append((values, options))
        return await evaluate(self, values, **options)

    monkeypatch.setattr(OmneumClient, '_evaluate_context', capture)

    async def run():
        results = []
        with benchmark_deployment() as (config, server):
            async with open_stdio_client(config, server) as client:
                for enabled in (False, True):
                    def experimental(*args, **kwargs):
                        return discovery(*args, **kwargs, conflict_aware=enabled)
                    monkeypatch.setattr(query_context, 'discover_chunks', experimental)
                    diagnostics = {}
                    result = await client.prepare_context(
                        observations, chunks, estimator=estimator_config(), token_budget=12,
                        strategy='coverage_support_density', complementary_evidence=True,
                        token_cost_exponent=1,
                        chunk_relevance={'0': 1., '1': 0.}, relevance_score_type='normalized',
                        candidate_discovery='expanded', candidate_count=1, expansion_depth=1,
                        query_diagnostics=diagnostics)
                    assert diagnostics.get('initial_eligible_chunk_ids', diagnostics['eligible_chunk_ids']) == (['0', '1'] if enabled else ['0'])
                    assert diagnostics['eligible_chunk_ids'] == ['0', '1']
                    assert diagnostics.get('recovered_chunk_ids', []) == []
                    assert result['selection']['selected_tokens'] <= 12
                    for chunk in result['chunks']:
                        assert chunk['raw_text'] == chunks[int(chunk['chunk_id'])]['raw_text']
                    results.append(result)
        assert results[0]['evaluation'] == results[1]['evaluation']
    asyncio.run(run())
    assert inputs[0] == inputs[1]
    assert len(inputs[0][0]) == len(observations)
    assert (observations, chunks) == original
