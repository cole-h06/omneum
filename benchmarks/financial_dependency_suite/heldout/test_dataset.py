"""Local artifact checks only: no selector, provider, daemon, or model execution."""
import hashlib
import json
import shutil

import pytest

from .loader import load_case
from .validate_dataset import ROOT, validate_case_files, validate_dataset

MATRIX = json.loads((ROOT / 'case_matrix.json').read_text())['cases']
PLAN = json.loads((ROOT / 'plan.json').read_text())


def test_complete_dataset():
    assert validate_dataset()['cases'] == 24


@pytest.mark.parametrize('spec', MATRIX, ids=lambda s: s['case_id'])
def test_each_case_loads_and_validates(spec):
    validate_case_files(ROOT / 'cases' / spec['case_id'], spec, PLAN)


def test_frozen_inputs():
    manifest = json.loads((ROOT / 'dataset_manifest.json').read_text())
    paths = {str(p.relative_to(ROOT)) for p in (ROOT / 'cases').glob('*/*.json')}
    assert paths == {p for p in manifest if p.startswith('cases/')}
    for relative, digest in manifest.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == digest, relative


def graph(case):
    sources = {c.source: i for i, c in enumerate(case.candidates)}
    assertions = {c.provenance.assertion_id: i for i, c in enumerate(case.candidates)}
    return {
        i: {sources[s] for s in c.provenance.upstream_sources + c.provenance.cited_sources}
        | {assertions[a] for a in c.provenance.parent_assertion_ids}
        for i, c in enumerate(case.candidates)
    }


def has_cycle(edges):
    def visit(node, active, done):
        if node in active:
            return True
        if node in done:
            return False
        active.add(node)
        if any(visit(child, active, done) for child in edges[node]):
            return True
        active.remove(node)
        done.add(node)
        return False
    done = set()
    return any(visit(node, set(), done) for node in edges)


@pytest.mark.parametrize('spec', MATRIX, ids=lambda s: s['case_id'])
def test_mechanism_structure(spec):
    case = load_case(ROOT / 'cases' / spec['case_id'] / 'case.json')
    edges = graph(case)
    mechanism = spec['mechanism']
    assert has_cycle(edges) == (mechanism == 'circular_sourcing')
    if mechanism == 'source_dependence':
        assert sum(bool(v) for v in edges.values()) >= 2
    if mechanism == 'staleness':
        dates = [c.provenance.source_modified_at for c in case.candidates]
        assert (max(dates) - min(dates)).days >= 10
        assert len({str(c.value) for c in case.candidates}) >= 2
    if mechanism == 'sparse_noisy_provenance':
        assert any(c.provenance.source_modified_at is None for c in case.candidates)
        assert any(c.provenance.cited_sources for c in case.candidates)
        assert any(c.provenance.upstream_sources for c in case.candidates)
    if mechanism == 'semantic_noise':
        assert len({(c.entity, c.attribute) for c in case.candidates}) >= 5
    if mechanism == 'independent_false_information':
        # Independently prompted agents / separately produced research estimates.
        # These positions are checked against authored scenario histories, not winners.
        indices = (0, 1, 2, 4) if case.case_id.startswith('research') else (0, 1, 2)
        assert len({str(case.candidates[i].value) for i in indices}) == 1
        assert all(not edges[i] for i in indices)
    if mechanism in ('conflicting_information', 'clean_control'):
        claims = {}
        for c in case.candidates:
            claims.setdefault((c.entity, c.attribute), set()).add(str(c.value))
        assert any(len(v) > 1 for v in claims.values()) == (mechanism == 'conflicting_information')


@pytest.mark.parametrize('mutation,match', [
    ('leak_field', 'unexpected fields'),
    ('leak_text', 'leakage'),
    ('leak_provenance', 'leakage'),
    ('dangling', 'dangling assertion'),
    ('source_role', 'source roles'),
    ('budget', 'budget mismatch'),
    ('count', 'candidate count'),
    ('timestamp', 'modified after'),
    ('support', 'unknown supporting'),
])
def test_audit_rejects_corrupted_artifacts(tmp_path, mutation, match):
    spec = MATRIX[1]
    directory = tmp_path / spec['case_id']
    shutil.copytree(ROOT / 'cases' / spec['case_id'], directory)
    path = directory / 'case.json'
    data = json.loads(path.read_text())
    first = data['candidates'][0]
    if mutation == 'leak_field':
        first['is_correct'] = True
    elif mutation == 'leak_text':
        first['text'] += ' Expected winner: current_api_docs.'
    elif mutation == 'leak_provenance':
        first['provenance']['assertion_id'] = 'ground_truth_source'
    elif mutation == 'dangling':
        first['provenance']['parent_assertion_ids'] = ['missing']
    elif mutation == 'source_role':
        first['source']['kind'] = 'report'
    elif mutation == 'budget':
        data['context_budget'] = 4
    elif mutation == 'count':
        data['candidates'].pop()
    elif mutation == 'timestamp':
        first['provenance']['source_modified_at'] = '2027-01-01T00:00:00Z'
    elif mutation == 'support':
        truth_path = directory / 'ground_truth.json'
        truth = json.loads(truth_path.read_text())
        truth['supporting_sources'].append('absent')
        truth_path.write_text(json.dumps(truth))
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match=match):
        validate_case_files(directory, spec, PLAN)


def test_missing_case_is_rejected(tmp_path):
    shutil.copytree(ROOT / 'cases', tmp_path / 'cases')
    for name in ('case_matrix.json', 'plan.json'):
        shutil.copyfile(ROOT / name, tmp_path / name)
    shutil.rmtree(tmp_path / 'cases' / MATRIX[-1]['case_id'])
    with pytest.raises(ValueError, match='case directories differ'):
        validate_dataset(tmp_path)
