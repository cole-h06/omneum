"""Filesystem-only regressions: never execute models or benchmark selections."""
import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from .execution_safety import (DEFAULT_TRACE, TRACE_SHA256, read_trace, recovery_analysis_preflight,
                               verify_recovery_analysis_protected_inputs,
                               RECOVERY_UNPUBLISHED_NON_INPUTS)
from .experiments import analyze_budget_recovery, budget_recovery


def contents(directory):
    return {str(p.relative_to(directory)): p.read_bytes()
            for p in directory.rglob('*') if p.is_file()}


@pytest.mark.parametrize('offline_only', [True, False])
@pytest.mark.parametrize('marker', ['selections.json', 'summary.json', 'validation.json',
                                   'analysis_validation.json', 'offline_validation.json',
                                   'manifest.json', 'alternatives.json', 'timings.csv'])
def test_recovery_refuses_completed_output_before_work(tmp_path, monkeypatch, offline_only, marker):
    (tmp_path / marker).write_bytes(b'frozen bytes\r\n')
    (tmp_path / 'existing-evidence.txt').write_bytes(b'preserved evidence')
    before = contents(tmp_path)
    monkeypatch.setattr(budget_recovery, 'evaluate_context',
                        lambda *a, **k: pytest.fail('graph evaluation'))
    monkeypatch.setattr(budget_recovery.httpx, 'Client',
                        lambda *a, **k: pytest.fail('tokenizer/model request'))
    with pytest.raises(FileExistsError, match='immutable'):
        asyncio.run(budget_recovery.run(SimpleNamespace(output=tmp_path, offline_only=offline_only)))
    assert contents(tmp_path) == before


def test_recovery_analysis_refuses_existing_destination(tmp_path):
    output = tmp_path / 'completed'
    output.mkdir()
    (output / 'report.md').write_bytes(b'published report')
    before = contents(tmp_path)
    with pytest.raises(FileExistsError, match='new output'):
        analyze_budget_recovery.main(output, source=tmp_path / 'missing')
    assert contents(tmp_path) == before


def test_analysis_missing_input_leaves_all_files_identical(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'selections.json').write_bytes(b'[]')
    before = contents(tmp_path)
    with pytest.raises(FileNotFoundError):
        analyze_budget_recovery.main(tmp_path / 'new-output', source=source)
    assert contents(tmp_path) == before
    assert not (tmp_path / 'new-output').exists()


def test_analysis_cannot_write_inside_its_frozen_inputs(tmp_path):
    source = tmp_path / 'frozen'
    source.mkdir()
    (source / 'selections.json').write_bytes(b'frozen selections')
    before = contents(tmp_path)
    with pytest.raises(ValueError, match='inside frozen inputs'):
        recovery_analysis_preflight(source, source / 'new-analysis')
    assert contents(tmp_path) == before


def test_analysis_bad_hash_is_rejected_before_output_creation(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    names = ('selections.json', 'timings.csv', 'manifest.json', 'validation.json',
             'protected_inputs.json', 'alternatives.json', 'positive-only-alternatives.json',
             'source_reliability_validation.json', 'production-change.patch',
             'selection-tests-verified.log')
    for name in names:
        (source / name).write_bytes(b'{}')
    (source / 'analysis_validation.json').write_text(json.dumps({
        'analysis_inputs_sha256': {'selections.json': hashlib.sha256(b'different').hexdigest()}}))
    before = contents(tmp_path)
    with pytest.raises(ValueError, match='input digest'):
        recovery_analysis_preflight(source, tmp_path / 'new-output')
    assert contents(tmp_path) == before
    assert not (tmp_path / 'new-output').exists()


def test_recovery_bad_preflight_preserves_existing_inputs(tmp_path):
    original = tmp_path / 'original.txt'
    original.write_bytes(b'original bytes')
    (tmp_path / 'protected_inputs.json').write_text(json.dumps({str(original): '0' * 64}))
    before = contents(tmp_path)
    with pytest.raises(ValueError, match='digest mismatch'):
        asyncio.run(budget_recovery.run(SimpleNamespace(output=tmp_path)))
    assert contents(tmp_path) == before


def test_final_recovery_preflight_is_read_only(tmp_path):
    source = Path(__file__).parent / 'results/budget-exhaustion-recovery-20261026-v2'
    before = contents(source)
    recovery_analysis_preflight(source, tmp_path / 'new-analysis')
    assert contents(source) == before
    assert not (tmp_path / 'new-analysis').exists()


def test_competitive_analysis_import_and_refusal_preserve_files(tmp_path):
    script = Path(__file__).parent / 'analysis/tier1-competitive-analysis-20261026-v1/analyze.py'
    before = contents(tmp_path)
    spec = importlib.util.spec_from_file_location('competitive_analysis_audit', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert contents(tmp_path) == before
    (tmp_path / 'report.md').write_bytes(b'existing report')
    before = contents(tmp_path)
    with pytest.raises(FileExistsError, match='new output'):
        module.main(tmp_path)
    assert contents(tmp_path) == before


def test_preserved_trace_has_original_hash_and_accepts_explicit_path(tmp_path):
    data = DEFAULT_TRACE.read_bytes()
    assert hashlib.sha256(data).hexdigest() == TRACE_SHA256
    explicit = tmp_path / 'trace.jsonl'
    explicit.write_bytes(data)
    assert read_trace(explicit) == read_trace()
    explicit.write_bytes(b'{}\n')
    with pytest.raises(ValueError, match='trace digest'):
        read_trace(explicit)


def test_execution_source_snapshots_resolve_with_original_hashes():
    from ..paths import resolve_artifact
    contract = Path(__file__).parent / 'contracts/execution-v1/sources.json'
    for name, digest in json.loads(contract.read_text()).items():
        resolved = resolve_artifact(name, expected_sha256=digest)
        assert hashlib.sha256(resolved.read_bytes()).hexdigest() == digest


@pytest.mark.parametrize('name', ['question_support_qualification_report',
                                'question_support_qualification_v4_report'])
def test_historical_report_import_and_refusal_do_not_write(tmp_path, name):
    import importlib
    module = importlib.import_module('benchmarks.context_selection.synthetic.' + name)
    (tmp_path / 'report.md').write_bytes(b'preserved report')
    before = contents(tmp_path)
    with pytest.raises(FileExistsError, match='new output'):
        module.main(tmp_path)
    assert contents(tmp_path) == before


def test_hardware_metadata_does_not_require_macos(monkeypatch):
    from . import tier1_benchmark
    monkeypatch.setattr(tier1_benchmark.sys, 'platform', 'linux')
    monkeypatch.setattr(tier1_benchmark.platform, 'platform', lambda: 'Linux')

    def git_only(command, **kwargs):
        assert command == ['git', 'rev-parse', 'HEAD']
        return 'reference-revision\n'

    monkeypatch.setattr(tier1_benchmark.subprocess, 'check_output', git_only)
    assert tier1_benchmark.environment()['hardware'] == {}


def test_public_analysis_scope_is_exact_and_execution_remains_strict():
    from .execution_safety import verify_hashes
    source = Path(__file__).parent / 'results/budget-exhaustion-recovery-20261026-v2'
    assert set(verify_recovery_analysis_protected_inputs(source)) == RECOVERY_UNPUBLISHED_NON_INPUTS
    with pytest.raises(ValueError, match='Protected input digest mismatch'):
        verify_hashes(json.loads((source / 'protected_inputs.json').read_text()),
                      allow_source_snapshots=True)


def test_unknown_manifest_cannot_exempt_missing_historical_files(tmp_path):
    source = Path(__file__).parent / 'results/budget-exhaustion-recovery-20261026-v2'
    content = (source / 'protected_inputs.json').read_bytes()
    (tmp_path / 'protected_inputs.json').write_bytes(content + b'\n')
    with pytest.raises(ValueError, match='Protected input digest mismatch'):
        verify_recovery_analysis_protected_inputs(tmp_path)


@pytest.mark.parametrize('state', ['missing', 'corrupt'])
def test_public_analysis_rejects_damaged_published_input_before_output(tmp_path, monkeypatch, state):
    from .. import paths
    source = Path(__file__).parent / 'results/budget-exhaustion-recovery-20261026-v2'
    entries = json.loads((source / 'protected_inputs.json').read_text())
    target = next(path for path in entries if '/canonical/cases/' in path and path.endswith('.json'))
    damaged = tmp_path / 'damaged.json'
    if state == 'corrupt':
        damaged.write_bytes(b'{}')
    resolve = paths.resolve_artifact
    monkeypatch.setattr(paths, 'resolve_artifact',
                        lambda path, **kw: damaged if path == target else resolve(path, **kw))
    with pytest.raises(ValueError, match='Protected input digest mismatch'):
        recovery_analysis_preflight(source, tmp_path / 'new-analysis')
    assert not (tmp_path / 'new-analysis').exists()


def test_supplied_unpublished_non_input_must_still_match(tmp_path, monkeypatch):
    from .. import paths
    source = Path(__file__).parent / 'results/budget-exhaustion-recovery-20261026-v2'
    target = sorted(RECOVERY_UNPUBLISHED_NON_INPUTS)[0]
    damaged = tmp_path / 'supplied-private-file'
    damaged.write_bytes(b'wrong bytes')
    resolve = paths.resolve_artifact
    monkeypatch.setattr(paths, 'resolve_artifact',
                        lambda path, **kw: damaged if path == target else resolve(path, **kw))
    with pytest.raises(ValueError, match='Protected input digest mismatch'):
        recovery_analysis_preflight(source, tmp_path / 'new-analysis')
    assert not (tmp_path / 'new-analysis').exists()
