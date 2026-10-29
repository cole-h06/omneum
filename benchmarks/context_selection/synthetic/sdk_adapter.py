"""Translate the frozen benchmark provenance schema into the public SDK.

The frozen loader and its manifest retain their original occurrence field
names. Keep this application boundary outside the frozen input artifacts.
"""
from omneum import Claim, Observation, Source, SourceReference

from .loader import _omneum_entity, _omneum_source
from .schema import candidate_claims


def build_observations(case):
    observations = []
    source_ids = {}

    for candidate in case.candidates:
        source = _omneum_source(candidate.source, Source)
        source_ids[source] = candidate.source_id

        provenance = candidate.provenance
        for spec in candidate_claims(candidate):
            entity_namespace, entity = _omneum_entity(spec.entity_namespace, spec.entity)
            claim = Claim(entity_namespace, entity, spec.attribute, spec.value)
            metadata = ({'chunk_id': 'chunk-' + candidate.source_id,
                         'canonical_claim_id': spec.claim_id,
                         'evidence': list(spec.evidence)} if candidate.claims else {})
            observations.append(Observation(
                observation_id=spec.observation_id, source=source, claim=claim,
                observed_at=provenance.observed_at,
                source_modified_at=provenance.source_modified_at,
                upstream_sources=tuple(_omneum_source(item, SourceReference)
                                       for item in provenance.upstream_sources),
                cited_sources=tuple(_omneum_source(item, SourceReference)
                                    for item in provenance.cited_sources),
                parent_observation_ids=provenance.parent_assertion_ids,
                retrievals=(), metadata=metadata,
            ))

    return tuple(observations), source_ids


def claim_from_record(record):
    """Read current claim JSON or historical dataclasses.asdict byte records."""
    import ast
    import json
    if 'value' in record:
        value = record['value']
    else:
        raw = record['_value_bytes']
        if isinstance(raw, str):
            # Historical artifact writer serialized bytes with default=str.
            raw = ast.literal_eval(raw)
        if type(raw) is not bytes:
            raise ValueError('invalid saved canonical claim bytes')
        value = json.loads(raw)
    return Claim(record['entity_namespace'], record['entity'], record['attribute'], value)


def observation_chunk_pairs(observations, chunks, case):
    """Join occurrences to original passages, never zip their different lengths.

    Accept live dataclasses or serialized benchmark inputs. Repeated diagnostic
    chunk copies keep the original source_id and therefore the same occurrences.
    """
    from collections.abc import Mapping
    from omneum.context_selection import claim_id
    def field(value, name):
        return value[name] if isinstance(value, Mapping) else getattr(value, name)
    def get(value, name, default=None):
        return value.get(name, default) if isinstance(value, Mapping) else getattr(value, name, default)
    members = {}
    for candidate in field(case, 'candidates'):
        specs = get(candidate, 'claims')
        ids = ([field(c, 'observation_id') for c in specs] if specs else
               [field(field(candidate, 'provenance'), 'assertion_id')])
        for oid in ids:
            if oid in members:
                raise ValueError('duplicate observation membership')
            members[oid] = field(candidate, 'source_id')
    by_source = {}
    for o in observations:
        oid = field(o, 'observation_id')
        if oid not in members:
            raise ValueError('observation has no candidate association')
        raw_claim = field(o, 'claim')
        cid = claim_id(claim_from_record(raw_claim) if isinstance(raw_claim, Mapping) else raw_claim)
        by_source.setdefault(members[oid], []).append((o, cid))
    result = []
    for chunk in chunks:
        associated = by_source.get(chunk['source_id'], [])
        mapped = set(chunk['claim_ids'])
        if mapped != {cid for _, cid in associated}:
            raise ValueError('chunk claims differ from associated observations')
        result.extend((o, chunk) for o, _ in associated)
    return result
