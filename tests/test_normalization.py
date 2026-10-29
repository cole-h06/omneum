import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import json

import pytest

from omneum import Claim, Observation, Source, normalize_observations, ContextMapper
from omneum.client import _evaluate_context
from omneum.context_selection import claim_id, reconstruct_context
from benchmarks.context_selection.config import estimator_config
from benchmarks.context_selection.synthetic.normalization_benchmark import graph_view


def observation(identifier, claim, *, source=None, parents=()):
    return Observation(identifier, source or Source('web_document', f'https://{identifier}.example'), claim,
        observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc), parent_observation_ids=parents,
        metadata={'chunk_id': identifier})


def fields(entity='pump', attribute='rated_pressure_kpa', value=200):
    return dict(entity_namespace='device', entity=entity, attribute=attribute, value=value)


class Provider:
    def __init__(self, claims, assignments):
        self.value = dict(claims=claims, assignments=assignments)
        self.prompts = []
    async def __call__(self, prompt):
        self.prompts.append(prompt)
        if json.loads(prompt.split('Input JSON:\n')[1]).get('phase') == 'verify':
            return {'text': json.dumps({'equivalent': True})}
        return {'text': json.dumps(self.value)}


def test_equivalents_conflicts_qualifications_and_provenance():
    original = (
        observation('a', Claim('device', 'Pump', 'rated_pressure_kpa', 200)),
        observation('b', Claim('device', 'pump', 'rated_pressure_kpa', 250)),
        observation('c', Claim('machine', 'the pump', 'pressure_rating', 200), parents=('a',)),
        observation('d', Claim('device', 'pump', 'safety_interlock', 'closed during startup')),
    )
    provider = Provider([fields(), fields(value=250), fields(attribute='safety_interlock', value='closed during startup')], [0, 1, 0, 2])
    result = asyncio.run(normalize_observations(original, provider=provider,
        chunk_texts={o.observation_id: 'Source text for ' + o.observation_id for o in original}))
    assert claim_id(result[0].claim) == claim_id(result[2].claim)
    assert result[0].claim.attribute == result[1].claim.attribute
    assert result[0].claim.value != result[1].claim.value
    assert len({claim_id(o.claim) for o in result}) == 3
    for old, new in zip(original, result):
        assert replace(new, claim=old.claim) == old
    assert result[2].parent_observation_ids == ('a',)
    evaluation = _evaluate_context(result, estimator=estimator_config())
    chunks = [dict(chunk_id=o.observation_id, raw_text='Original ' + o.observation_id,
                   claim_ids=[claim_id(o.claim)]) for o in result]
    selected = reconstruct_context(evaluation, chunks, token_budget=1000, strategy='coverage_support_query',
        claim_relevance={claim_id(o.claim): 1. for o in result})
    assert len(selected['selected_chunk_ids']) == 3  # both conflicting values and the distinct interlock
    assert selected['claim_coverage'] == {'covered': 3, 'total': 3}


@pytest.mark.parametrize('claims,assignments,error', [
    ([fields()], [0], 'cover every'),
    ([fields()], [0, True], 'cover every'),
    ([fields(), fields()], [0, 1], 'duplicate canonical'),
    ([fields(), fields(value=250)], [0, 0], 'unused'),
    ([fields(value=201)], [0, 0], 'numeric'),
])
def test_invalid_catalogs_fail_closed(claims, assignments, error):
    observations = [observation('a', Claim(**fields())), observation('b', Claim(**fields()))]
    try:
        result = asyncio.run(normalize_observations(observations, provider=Provider(claims, assignments)))
    except ValueError as failure:
        assert error in str(failure)
    else:
        # A malformed catalog may safely recover exact original identities,
        # but must never apply a guessed change or lose an occurrence.
        assert result == tuple(observations)


def test_conflict_cannot_be_hidden_or_values_collapsed():
    values = [observation('a', Claim(**fields(value='open'))), observation('b', Claim(**fields(value='closed')))]
    with pytest.raises(ValueError, match='conflicting values collapsed'):
        asyncio.run(normalize_observations(values, provider=Provider([fields(value='open')], [0, 0])))
    with pytest.raises(ValueError, match='property identity'):
        asyncio.run(normalize_observations(values, provider=Provider(
            [fields(value='open'), fields(attribute='other_pressure', value='closed')], [0, 1])))


def test_repeated_occurrence_identity_and_graph_aliases():
    source = Source('web_document', 'https://one.example')
    a = observation('a', Claim(**fields()), source=source)
    duplicate = replace(a, observation_id='repeat', metadata={'chunk_id': 'second-passage'})
    child = observation('child', Claim(**fields(value=250)), parents=('repeat',))
    normalized = asyncio.run(normalize_observations([a, duplicate, child], provider=Provider(
        [fields(), fields(value=250)], [0, 0, 1])))
    graph, aliases = graph_view(normalized)
    assert len(normalized) == 3 and len(graph) == 2
    assert aliases == {'a': 'a', 'repeat': 'a', 'child': 'child'}
    assert graph[1].parent_observation_ids == ('a',)
    assert normalized[1].metadata['chunk_id'] == 'second-passage'
    _evaluate_context(graph, estimator=estimator_config())


def test_incompatible_occurrence_provenance_is_not_silently_dropped():
    a = observation('a', Claim(**fields()))
    with pytest.raises(ValueError, match='different provenance'):
        graph_view([a, replace(a, observation_id='b', source_modified_at=a.observed_at)])
    with pytest.raises(ValueError, match='different provenance'):
        graph_view([a, replace(a, observation_id='b', dependency_signals={'lineage': 'distinct'})])


def test_existing_mapper_contract_and_deterministic_reconstruction():
    mapper = ContextMapper(source='source', entity_namespace='namespace', entity='entity', attribute='predicate',
        value='value', observation_id='id', observed_at='time', metadata={'chunk_id': 'chunk'})
    records = [dict(source=Source('web_document', 'https://source.example'), namespace='device', entity='pump',
        predicate='pressure', value=200, id='p', time=datetime(2026, 1, 1, tzinfo=timezone.utc), chunk='raw')]
    values = mapper.map_many(records)
    normalized = asyncio.run(normalize_observations(values, provider=Provider([fields()], [0])))
    evaluation = _evaluate_context(normalized, estimator=estimator_config())
    chunks = [dict(chunk_id='raw', raw_text=' Original\r\n😀', claim_ids=[claim_id(normalized[0].claim)])]
    options = dict(token_budget=100, strategy='coverage_support_query', claim_relevance={claim_id(normalized[0].claim): .8})
    first = reconstruct_context(evaluation, chunks, **options)
    assert first == reconstruct_context(evaluation, chunks, **options)
    assert first['context'] == '[raw]\n Original\r\n😀'


def test_aligned_records_restore_repeated_occurrences_without_model_indices():
    a = observation('a', Claim(**fields()))
    b = observation('b', Claim(**fields()))
    c = observation('c', Claim('machine', 'the pump', 'pressure_rating', 200))
    async def provider(prompt):
        request = json.loads(prompt.split('Input JSON:\n')[1])
        if request.get('phase') == 'verify':
            return {'text': json.dumps({'equivalent': True})}
        assert len(request['observations']) == 2
        return {'text': json.dumps({'observations': [fields(), fields()]})}
    values = asyncio.run(normalize_observations([a, b, c], provider=provider))
    assert [v.observation_id for v in values] == ['a', 'b', 'c']
    assert len({claim_id(v.claim) for v in values}) == 1


def test_bounded_reassignment_keeps_original_identity_available():
    a = observation('a', Claim(**fields()))
    async def provider(prompt):
        request = json.loads(prompt.split('Input JSON:\n')[1])
        if request.get('phase') == 'assignment':
            catalog = request['catalog']
            matching = next(c['index'] for c in catalog if c['value'] == 200)
            return {'text': json.dumps({'assignments': [matching]})}
        return {'text': json.dumps({'claims': [fields(value=201)], 'assignments': [99]})}
    values = asyncio.run(normalize_observations([a], provider=provider))
    assert values == (a,)


def test_sdk_normalized_claims_and_chunk_associations_remain_payload_blind(monkeypatch):
    from omneum import coalesce_observations, open_stdio_client
    from omneum.mcp import ClientSession
    from benchmarks.context_selection.deployment import benchmark_deployment
    original = [observation('a', Claim(**fields())),
                observation('b', Claim('machine', 'the pump', 'pressure_rating', 200), parents=('a',)),
                observation('c', Claim(**fields(value=250))),
                observation('d', Claim(**fields(attribute='startup_interlock', value='closed')))]
    normalized = asyncio.run(normalize_observations(original, provider=Provider(
        [fields(), fields(value=250), fields(attribute='startup_interlock', value='closed')], [0, 0, 1, 2])))
    graph, aliases = coalesce_observations(normalized)
    chunks = [dict(chunk_id=o.metadata['chunk_id'], raw_text='PRIVATE original evidence ' + o.observation_id + '\r\n😀',
                   source=o.source, claim_ids=[claim_id(o.claim)]) for o in normalized]
    wire = []
    call = ClientSession.call_tool
    async def capture(self, name, arguments=None, *args, **kwargs):
        if name == 'evaluate_context':
            wire.append(arguments)
        return await call(self, name, arguments, *args, **kwargs)
    monkeypatch.setattr(ClientSession, 'call_tool', capture)
    async def run():
        with benchmark_deployment() as (config, server):
            async with open_stdio_client(config, server) as client:
                result = await client.prepare_context(graph, chunks, estimator=estimator_config(), token_budget=1000,
                    strategy='coverage_support_query', claim_relevance={claim_id(o.claim): 1. for o in normalized},
                    query_anchoring=False)
                assert len(result['packed_chunk_ids']) == 3
                assert any(c['chunk_id'] == 'd' for c in result['chunks'])
                assert all(c['raw_text'].endswith('\r\n😀') for c in result['chunks'])
    asyncio.run(run())
    assert aliases == {o.observation_id: o.observation_id for o in normalized}
    assert 'PRIVATE original evidence' not in json.dumps(wire)


def test_coalescing_canonical_source_aliases_and_unknown_parents():
    from omneum import coalesce_observations
    a = observation('a', Claim(**fields()), source=Source('web_document', 'https://EXAMPLE.com/a'))
    b = replace(a, observation_id='b', source=Source('web_document', 'https://example.com/a'))
    graph, aliases = coalesce_observations([a, b])
    assert len(graph) == 1 and aliases['b'] == 'a'
    with pytest.raises(ValueError, match='ownership'):
        coalesce_observations([a, replace(b, source=replace(b.source, owner_id='different'))])
    with pytest.raises(ValueError, match='unknown parent'):
        coalesce_observations([replace(a, parent_observation_ids=('missing',))])


def test_semantically_rejected_alias_retains_distinct_fact_and_metadata():
    a = observation('a', Claim(**fields()))
    async def provider(prompt):
        request = json.loads(prompt.split('Input JSON:\n')[1])
        if request.get('phase') == 'verify':
            assert request['original']['attribute'] != request['proposed']['attribute']
            return {'text': json.dumps({'equivalent': False})}
        return {'text': json.dumps({'observations': [fields(attribute='mass_grams')]})}
    assert asyncio.run(normalize_observations([a], provider=provider)) == (a,)


def test_partial_semantic_acceptance_cannot_scatter_conflicting_values():
    a = observation('a', Claim(**fields()))
    b = observation('b', Claim(**fields(value=250)))
    async def provider(prompt):
        request = json.loads(prompt.split('Input JSON:\n')[1])
        if request.get('phase') == 'verify':
            return {'text': json.dumps({'equivalent': request['original']['value'] == 200})}
        return {'text': json.dumps({'observations': [fields(entity='pump-alias'), fields(entity='pump-alias', value=250)]})}
    values = asyncio.run(normalize_observations([a, b], provider=provider))
    assert values == (a, b)


def test_verified_property_aliases_apply_to_conflicts_but_not_distinct_facts():
    values = [observation('a', Claim('device', 'pump', 'pressure_rating', 200)),
              observation('b', Claim('equipment', 'pump', 'rated_pressure', 200)),
              observation('c', Claim('equipment', 'pump', 'rated_pressure', 250)),
              observation('d', Claim('equipment', 'pump', 'power_rating', 200))]
    async def provider(prompt):
        request = json.loads(prompt.split('Input JSON:\n')[1])
        if request.get('phase') == 'verify':
            left, right = request['original']['attribute'], request['proposed']['attribute']
            return {'text': json.dumps({'equivalent': 'pressure' in left and 'pressure' in right})}
        return {'text': json.dumps({'observations': [dict(entity_namespace=o.claim.entity_namespace,
            entity=o.claim.entity, attribute=o.claim.attribute, value=o.claim.value) for o in values]})}
    normalized = asyncio.run(normalize_observations(values, provider=provider))
    assert claim_id(normalized[0].claim) == claim_id(normalized[1].claim)
    assert normalized[0].claim.attribute == normalized[2].claim.attribute
    assert normalized[0].claim.value != normalized[2].claim.value
    assert normalized[3].claim.attribute == 'power_rating'
    assert len({claim_id(o.claim) for o in normalized}) == 3


def test_caller_registry_preserves_scoped_property_identity_and_conflicts():
    from omneum.normalization import align_claim_properties
    scoped = Claim('analytics', 'Orion July 2026 paid seats', 'seat_count', 200)
    values = [observation('a', scoped),
              observation('b', Claim('API', 'paid seats', 'value', 200)),
              observation('c', Claim('API', 'paid seats', 'value', 250))]
    async def provider(prompt):
        return {'text': json.dumps({'equivalent': True})}
    normalized = asyncio.run(align_claim_properties(values, provider=provider,
        canonical_claims=[Claim(scoped.entity_namespace, scoped.entity, scoped.attribute,
                               'registry values do not choose truth')]))
    assert claim_id(normalized[0].claim) == claim_id(scoped)
    assert claim_id(normalized[0].claim) == claim_id(normalized[1].claim)
    assert claim_id(normalized[2].claim) == claim_id(Claim(scoped.entity_namespace, scoped.entity, scoped.attribute, 250))
    assert [o.observation_id for o in normalized] == ['a', 'b', 'c']
    assert [o.metadata for o in normalized] == [o.metadata for o in values]


def test_alias_union_cannot_introduce_source_conflict_even_if_provider_approves():
    from omneum.normalization import align_claim_properties
    source = Source('web_document', 'https://same.example')
    values = [observation('a', Claim('device', 'pump', 'pressure', 200), source=source),
              observation('b', Claim('device', 'pump', 'pressure_limit', 250), source=source),
              observation('c', Claim('device', 'pump', 'pressure_limit', 200))]
    async def provider(prompt):
        return {'text': json.dumps({'equivalent': True})}
    normalized = asyncio.run(align_claim_properties(values, provider=provider))
    assert [claim_id(o.claim) for o in normalized] == [claim_id(o.claim) for o in values]
    _evaluate_context(normalized, estimator=estimator_config())


def test_invalid_supplemental_chunk_cannot_erase_other_chunks_or_original_mapping():
    from benchmarks.context_selection.synthetic.normalization_followup import _retain_valid_supplemental
    anchors = [observation('a', Claim(**fields())), observation('b', Claim(**fields()))]
    supplemental = [replace(anchors[0], observation_id='extra-a',
        claim=Claim('device', 'pump', 'interlock', 'closed'))]
    invalid = [replace(anchors[1], observation_id='extra-b', claim=Claim(**fields(value=250)))]
    retained, error = _retain_valid_supplemental(anchors,supplemental,invalid)
    assert retained == tuple(supplemental) and 'multiple claims' in error
    assert [o.observation_id for o in (*anchors,*retained)] == ['a','b','extra-a']
    _evaluate_context(graph_view((*anchors,*retained))[0], estimator=estimator_config())


def test_complete_claim_paraphrases_can_match_catalog_without_literal_value_equality():
    from omneum.normalization import _align_claim_identities
    target = Claim('equipment', 'pump', 'drive_mode', 'disconnect drive')
    conflict = Claim('equipment', 'pump', 'drive_mode', 'engage drive')
    values = [observation('a', target),
        observation('b', Claim('machine', 'pump', 'mechanical_state', 'drive decoupled')),
        observation('c', Claim('machine', 'pump', 'mechanical_state', 'drive decoupled')),
        observation('detail', Claim('machine', 'pump', 'disconnect_requires_lockout', True))]
    async def provider(prompt):
        request=json.loads(prompt.split('Input JSON:\n')[1])
        equivalent=(request['original']['value']=='drive decoupled' and request['proposed']['value']=='disconnect drive')
        return {'text':json.dumps({'equivalent':equivalent})}
    normalized=asyncio.run(_align_claim_identities(values,provider=provider,canonical_claims=[target,conflict]))
    assert len({claim_id(o.claim) for o in normalized})==2
    assert [claim_id(o.claim) for o in normalized[:3]]==[claim_id(target)]*3
    assert normalized[-1]==values[-1]
    assert [o.metadata for o in normalized]==[o.metadata for o in values]


def test_catalog_matching_cannot_change_numeric_magnitude_or_source_consistency():
    from omneum.normalization import _align_claim_identities
    source=Source('web_document','https://one.example')
    values=[observation('a', Claim('machine','pump','operating_pressure',200),source=source),
            observation('b', Claim('machine','pump','pressure_limit',250),source=source)]
    async def provider(prompt):
        return {'text':json.dumps({'equivalent':True})}
    normalized=asyncio.run(_align_claim_identities(values,provider=provider,
        canonical_claims=[Claim('machine','pump','operating_pressure',250)]))
    assert normalized==tuple(values)


def test_atomic_matching_includes_non_catalog_claims_but_keeps_conditions():
    from omneum.normalization import _align_atomic_claims
    values=[observation('a',Claim('device','pump','pressure_rating',200)),
        observation('b',Claim('equipment','pump','rated_pressure',200),parents=('a',)),
        observation('c',Claim('device','pump','startup_pressure',{'condition':'guard closed','consequence':200}))]
    async def provider(prompt):
        payload=json.loads(prompt.split('Input JSON:\n')[1])
        if payload['phase']=='verify':
            return {'text':json.dumps({'equivalent':{payload['original']['attribute'],payload['proposed']['attribute']}=={'pressure_rating','rated_pressure'}})}
        assert payload['phase']=='atomic_equivalence'
        decisions=[{p['left']['attribute'],p['right']['attribute']}=={'pressure_rating','rated_pressure'} for p in payload['pairs']]
        return {'text':json.dumps({'equivalent':decisions})}
    normalized=asyncio.run(_align_atomic_claims(values,provider=provider))
    assert claim_id(normalized[0].claim)==claim_id(normalized[1].claim)
    assert normalized[2]==values[2]
    assert normalized[1].parent_observation_ids==('a',)
    for before,after in zip(values,normalized):assert replace(after,claim=before.claim)==before


def test_atomic_matching_rejects_incomplete_decisions_and_hidden_conflicts():
    from omneum.normalization import _align_atomic_claims
    values=[observation('a',Claim('device','pump','pressure_rating',200)),
        observation('b',Claim('device','pump','pressure_rating',250)),
        observation('c',Claim('equipment','pump','rated_pressure',200))]
    async def malformed(prompt):return {'text':'{"equivalent":[]}'}
    assert asyncio.run(_align_atomic_claims(values,provider=malformed))==tuple(values)
    async def approve(prompt):
        payload=json.loads(prompt.split('Input JSON:\n')[1])
        if payload['phase']=='verify':return {'text':'{"equivalent":true}'}
        return {'text':json.dumps({'equivalent':[True]*len(payload['pairs'])})}
    normalized=asyncio.run(_align_atomic_claims(values,provider=approve,canonical_claims=[values[2].claim]))
    assert [claim_id(o.claim) for o in normalized]==[claim_id(o.claim) for o in values]


def test_atomic_batch_approval_is_not_authority_without_strict_verification():
    from omneum.normalization import _align_atomic_claims
    values=[observation('a',Claim('device','pump','inspection_date','June 20')),
            observation('b',Claim('device','pump','service_definition','inspect seals'))]
    phases=[]
    async def provider(prompt):
        payload=json.loads(prompt.split('Input JSON:\n')[1]);phases.append(payload['phase'])
        if payload['phase']=='verify':return {'text':'{"equivalent":false}'}
        return {'text':json.dumps({'equivalent':[True]*len(payload['pairs'])})}
    assert asyncio.run(_align_atomic_claims(values,provider=provider))==tuple(values)
    assert phases==[]  # Different literal quantities now block this pair before model calls.


def test_existing_normalization_api_atomic_stage_drives_real_graph_and_coverage():
    values=[observation('a',Claim('device','pump','shaft_state','drive disengaged')),
            observation('b',Claim('machine','pump','coupling_state','drive disconnected'),parents=('a',))]
    async def provider(prompt):
        payload=json.loads(prompt.split('Input JSON:\n')[1])
        if payload.get('phase')=='verify':return {'text':'{"equivalent":true}'}
        if payload.get('phase')=='atomic_equivalence':
            return {'text':json.dumps({'equivalent':[True]*len(payload['pairs'])})}
        return {'text':json.dumps({'observations':[{k:o[k] for k in ('entity_namespace','entity','attribute','value')} for o in payload['observations']]})}
    normalized=asyncio.run(normalize_observations(values,provider=provider))
    assert len({claim_id(o.claim) for o in normalized})==1
    graph,_=graph_view(normalized)
    evaluation=_evaluate_context(graph,estimator=estimator_config())
    texts=['Original shaft evidence\r\n😀','Original copied coupling evidence']
    chunks=[dict(chunk_id=o.observation_id,raw_text=t,claim_ids=[claim_id(o.claim)]) for o,t in zip(normalized,texts,strict=True)]
    result=reconstruct_context(evaluation,chunks,token_budget=1000,strategy='coverage_support_query',claim_relevance={claim_id(normalized[0].claim):1.})
    assert len(result['selected_chunk_ids'])==1
    assert result['chunks'][0]['raw_text'] in texts
    assert normalized[1].parent_observation_ids==('a',)


def test_verification_cache_is_scoped_to_original_chunk_and_source_text():
    from omneum.normalization import _verify_changes
    old=Claim('software','server','port',8080)
    target=Claim('software','server production','readiness_port',8080)
    original=(observation('a',old),observation('b',old))
    proposed=tuple(replace(o,claim=target) for o in original)
    prompts=[]
    async def provider(prompt):
        payload=json.loads(prompt.split('Input JSON:\n')[1]);prompts.append(payload)
        return {'text':json.dumps({'equivalent':payload['original_chunk_id']=='a'})}
    result=asyncio.run(_verify_changes(original,proposed,provider,{'a':'Production port 8080.','b':'Direct binary default 8080.'}))
    assert len(prompts)==2
    assert prompts[0]['original_source_text']=='Production port 8080.'
    assert prompts[1]['original_source_text']=='Direct binary default 8080.'
    assert result[0].claim==target and result[1].claim==old
