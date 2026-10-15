"""Verify recovered publication evidence offline, including corruption rejection."""
import shutil

import pytest

from .verify_gemini_recovery import BASE, RUN, verify


def test_canonical_records_and_matching_baseline():
    manifest, rows, audit, comparison = verify()
    assert len(rows) == len(audit) == 480
    assert len(manifest['source_preservation']['target_source_record_sha256']) == 139
    assert comparison['counts']['bge_google'] == {'correct': 230, 'generator_refusal': 10}


def test_corrupted_raw_results_are_rejected(tmp_path):
    shutil.copytree(BASE / 'results' / RUN, tmp_path / 'results' / RUN)
    shutil.copytree(BASE / 'analysis' / RUN, tmp_path / 'analysis' / RUN)
    raw = tmp_path / 'results' / RUN / 'results.jsonl'
    raw.write_bytes(raw.read_bytes() + b'\n')
    with pytest.raises(ValueError, match='artifact changed: results.jsonl'):
        verify(tmp_path)
