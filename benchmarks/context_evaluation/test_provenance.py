"""Public evidence identity, projection and fresh-checkout integrity."""
import hashlib
import json
from copy import deepcopy
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from .paths import ROOT, input_digest, resolve_artifact, verify_recorded_artifact, publication_contract
from .heldout import build_dashboard_summary as dashboard


def test_relocated_inputs_require_matching_digest_and_identity():
    fixture = ROOT / "benchmarks/context_evaluation/heldout/cases/coding_config_conflict/case.json"
    digest = hashlib.sha256(fixture.read_bytes()).hexdigest()
    recorded = "/another/checkout/benchmarks/financial_dependency_suite/heldout/cases/coding_config_conflict/case.json"
    assert input_digest({recorded: digest}, fixture) == digest
    assert input_digest({recorded.replace("coding_config_conflict", "unknown"): digest}, fixture) is None
    with pytest.raises(ValueError, match="Conflicting"):
        input_digest({recorded: digest, str(fixture): "different"}, fixture)
    with pytest.raises(ValueError, match="escapes"):
        resolve_artifact("benchmarks/financial_dependency_suite/../secret")


def test_v2_sources_are_archived_without_rehashing():
    base = dashboard.BASE
    for name, digest in json.loads((base / "source_manifest_v2.json").read_text()).items():
        assert hashlib.sha256((base / "contracts/v2" / f"{name}.txt").read_bytes()).hexdigest() == digest


def test_publication_inventory_is_verified():
    assert dashboard.verify_publication_evidence()["version"] == 1


@pytest.mark.parametrize('name,key', [
    ('publication_manifest_v1.json', 'artifacts'),
    ('heldout/source_manifest_v5.json', 'sha256'),
])
def test_reviewed_contract_revisions_preserve_previous_contract_bytes(name, key):
    contract = json.loads((Path(__file__).parent / name).read_text())
    previous = deepcopy(contract)
    while previous.get('revision_history'):
        revision = previous['revision_history'].pop()
        for path, change in revision['changes'].items():
            assert previous[key][path] == change['sha256']
            assert change['reason']
            previous[key][path] = change['previous_sha256']
        if not previous['revision_history']:
            del previous['revision_history']
        encoded = (json.dumps(previous, indent=2) + '\n').encode()
        assert hashlib.sha256(encoded).hexdigest() == revision['previous_contract_sha256']


def test_public_projections_never_claim_original_byte_identity():
    for name, entry in publication_contract()["representations"].items():
        path = verify_recorded_artifact(name, entry["original_sha256"])
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]
        assert entry["sha256"] != entry["original_sha256"]
        assert not (ROOT / name).exists()
        with pytest.raises(ValueError, match="digest mismatch"):
            resolve_artifact(name, expected_sha256=entry["original_sha256"])
        with pytest.raises(ValueError, match="Original evidence digest mismatch"):
            verify_recorded_artifact(name, "0" * 64)


def test_corrupted_public_projection_is_rejected(tmp_path):
    contract = publication_contract()
    name, entry = next(iter(contract["representations"].items()))
    contract_path = tmp_path / "benchmarks/context_evaluation/publication_manifest_v1.json"
    contract_path.parent.mkdir(parents=True)
    contract_path.write_text(json.dumps(contract))
    artifact = tmp_path / entry["path"]
    artifact.parent.mkdir(parents=True)
    artifact.write_text("{}")
    with pytest.raises(ValueError, match="Public representation digest mismatch"):
        verify_recorded_artifact(name, entry["original_sha256"], root=tmp_path)


def test_fresh_checkout_verifies_without_git_or_old_directory(tmp_path):
    for directory in ("benchmarks", "omneum"):
        shutil.copytree(ROOT / directory, tmp_path / directory,
                        ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"))
    (tmp_path / "tools").mkdir()
    shutil.copy2(ROOT / "tools/run_context_evaluation_tests.py", tmp_path / "tools")
    assert not (tmp_path / "benchmarks/financial_dependency_suite").exists()
    assert not any(path.is_symlink() for path in (tmp_path / "benchmarks").rglob("*"))
    code = """
import importlib
try:
    importlib.import_module('benchmarks.financial_dependency_suite')
except ModuleNotFoundError:
    pass
else:
    raise AssertionError('Retired package alias remains active')
from benchmarks.context_evaluation.heldout.build_dashboard_summary import build_summary
from benchmarks.context_evaluation.paths import resolve_artifact
assert resolve_artifact('/previous/machine/benchmarks/financial_dependency_suite/heldout/cases/coding_config_conflict/case.json').is_file()
assert len(build_summary()['configurations']) == 12
"""
    subprocess.run([sys.executable, "-B", "-c", code], cwd=tmp_path, check=True)


def test_publication_contract_schema_and_current_source_contract():
    from jsonschema import Draft202012Validator

    schema = json.loads((Path(__file__).parent / "publication_manifest_v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(publication_contract())
    manifest = json.loads((dashboard.BASE / "source_manifest_v5.json").read_text())
    for name, digest in manifest["sha256"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
