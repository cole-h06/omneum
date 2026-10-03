"""Offline dataset audit. Does not import selectors or call benchmark methods."""
import json
import re
from collections import Counter
from pathlib import Path

from .loader import application_candidates, build_observations, load_case, load_ground_truth
from .scoring import score_answer

ROOT = Path(__file__).parent
CANONICAL = 'coding_package_fix_lineage'
# The pre-existing example uses transport kinds rather than matrix source roles.
CANONICAL_IDS = (
    'issue_origin', 'issue_comment', 'community_note', 'repository_code',
    'release_notes', 'package_docs', 'test_output', 'pull_request',
)
KNOWN_ISSUES = (
    'coding_package_fix_lineage: matrix slot 3 is issue_comment, but the preserved '
    'canonical candidate is a community note at /community/pool-workaround.',
)
LEAKAGE = re.compile(
    r'\b(?:ground[ _-]?truth|supporting[ _-]sources|expected[ _-](?:winner|answer)|'
    r'gold[ _-](?:label|answer)|(?:correctness|oracle)[ _-]label|'
    r'(?:correct|incorrect)[ _-](?:candidate|source)|'
    r'(?:braid|cohere|bge)[ _-](?:winner|preferred)|'
    r'(?:select|rank) (?:this|me) (?:candidate|first))\b', re.I,
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def fields(data, required, optional=()):
    require(isinstance(data, dict), 'expected object')
    require(set(required) <= data.keys(), f'missing fields: {set(required) - data.keys()}')
    require(data.keys() <= set(required) | set(optional), f'unexpected fields: {data.keys() - set(required) - set(optional)}')


def string(value):
    require(isinstance(value, str) and bool(value.strip()), 'expected nonempty string')


def source(value):
    fields(value, ('kind', 'identifier'))
    for item in value.values():
        string(item)


def validate_case_files(directory, spec, plan):
    raw = json.loads((directory / 'case.json').read_text())
    labels = json.loads((directory / 'ground_truth.json').read_text())
    fields(raw, ('id', 'domain', 'question', 'context_budget', 'candidates'))
    require(raw['id'] == spec['case_id'] == directory.name, 'case ID mismatch')
    require(raw['domain'] == spec['environment'], 'environment mismatch')
    string(raw['question'])
    require(type(raw['context_budget']) is int, 'budget must be an integer')
    require(raw['context_budget'] == spec['context_budget'], 'matrix budget mismatch')
    require(plan['context_budget']['minimum'] <= raw['context_budget'] <= plan['context_budget']['maximum'], 'plan budget mismatch')
    require(isinstance(raw['candidates'], list), 'candidates must be a list')
    require(len(raw['candidates']) == spec['candidate_count'], 'matrix candidate count mismatch')
    require(plan['candidate_count']['minimum'] <= len(raw['candidates']) <= plan['candidate_count']['maximum'], 'plan candidate count mismatch')
    require(raw['context_budget'] <= len(raw['candidates']), 'budget exceeds pool')
    require(not LEAKAGE.search(json.dumps(raw).replace("_", " ")), 'obvious ground-truth leakage')
    for item in raw['candidates']:
        fields(item, ('source_id', 'source', 'text', 'entity_namespace', 'entity', 'attribute', 'value', 'provenance'))
        for key in ('source_id', 'text', 'entity_namespace', 'entity', 'attribute'):
            string(item[key])
        source(item['source'])
        provenance = item['provenance']
        fields(provenance, ('assertion_id', 'observed_at'), ('source_modified_at', 'upstream_sources', 'cited_sources', 'parent_assertion_ids'))
        string(provenance['assertion_id'])
        string(provenance['observed_at'])
        for key in ('upstream_sources', 'cited_sources', 'parent_assertion_ids'):
            require(isinstance(provenance.get(key, []), list), f'{key} must be a list')
        for key in ('upstream_sources', 'cited_sources'):
            for reference in provenance.get(key, []):
                source(reference)
        for parent in provenance.get('parent_assertion_ids', []):
            string(parent)
    if raw['id'] == CANONICAL:
        require(tuple(c['source_id'] for c in raw['candidates']) == CANONICAL_IDS, 'canonical IDs changed')
    else:
        require([c['source']['kind'] for c in raw['candidates']] == spec['sources'], 'matrix source roles mismatch')
    fields(labels, ('case_id', 'answer', 'supporting_sources', 'scoring'))
    require(labels['case_id'] == raw['id'], 'truth ID mismatch')
    string(labels['answer'])
    require(isinstance(labels['supporting_sources'], list) and labels['supporting_sources'], 'empty support set')
    fields(labels['scoring'], ('required', 'forbidden'))
    for key in ('required', 'forbidden'):
        require(isinstance(labels['scoring'][key], list), 'scoring terms must be lists')
        for term in labels['scoring'][key]:
            string(term)
    require(labels['scoring']['required'], 'empty scoring requirements')
    case = load_case(directory / 'case.json')
    truth = load_ground_truth(directory / 'ground_truth.json')
    ids = {c.source_id for c in case.candidates}
    assertions = {c.provenance.assertion_id for c in case.candidates}
    sources = {c.source for c in case.candidates}
    require(len(ids) == len(assertions) == len(sources) == len(case.candidates), 'duplicate source or assertion')
    require(set(truth.supporting_sources) <= ids, 'unknown supporting source')
    require(len(set(truth.supporting_sources)) == len(truth.supporting_sources), 'duplicate support label')
    require(score_answer(truth.answer, truth) == 'correct', 'reference answer fails existing scorer')
    for candidate in case.candidates:
        p = candidate.provenance
        require(p.observed_at.tzinfo is not None, 'naive observation timestamp')
        if p.source_modified_at is not None:
            require(p.source_modified_at.tzinfo is not None, 'naive modification timestamp')
            require(p.source_modified_at <= p.observed_at, 'modified after observation')
        require(set(p.parent_assertion_ids) <= assertions, 'dangling assertion reference')
        require(p.assertion_id not in p.parent_assertion_ids, 'self assertion reference')
        require(set(p.upstream_sources + p.cited_sources) <= sources, 'dangling source reference')
        require(candidate.source not in p.upstream_sources + p.cited_sources, 'self source reference')
    observations, source_ids = build_observations(case)
    require(len(observations) == len(source_ids) == len(case.candidates), 'observation conversion lost candidates')
    require(application_candidates(case) == [{'source': c.source_id, 'text': c.text} for c in case.candidates], 'application pool changed')
    return case


def validate_dataset(root=ROOT):
    matrix = json.loads((root / 'case_matrix.json').read_text())['cases']
    plan = json.loads((root / 'plan.json').read_text())
    names = {s['case_id'] for s in matrix}
    require(len(matrix) == len(names) == plan['case_count'] == 24, 'matrix cardinality mismatch')
    require(Counter(s['environment'] for s in matrix) == plan['environments'], 'environment totals mismatch')
    require(Counter(s['mechanism'] for s in matrix) == plan['mechanisms'], 'mechanism totals mismatch')
    directories = {p.name for p in (root / 'cases').iterdir() if p.is_dir()}
    require(directories == names, f'case directories differ: {directories ^ names}')
    for spec in matrix:
        directory = root / 'cases' / spec['case_id']
        require({p.name for p in directory.iterdir()} == {'case.json', 'ground_truth.json'}, f'incomplete case: {directory.name}')
        try:
            validate_case_files(directory, spec, plan)
        except (ValueError, TypeError, KeyError) as error:
            raise ValueError(f'{directory.name}: {error}') from error
    return {'cases': len(names), 'environments': plan['environments'], 'mechanisms': plan['mechanisms'], 'known_issues': list(KNOWN_ISSUES)}


if __name__ == '__main__':
    print(json.dumps(validate_dataset(), indent=2))
