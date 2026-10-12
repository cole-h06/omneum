"""Verify recovered publication evidence offline, including corruption rejection."""
import hashlib
import json
from pathlib import Path
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


def test_chart_data_matches_all_published_selection_medians():
    root = BASE.parents[2]
    data = json.loads((root / 'assets/benchmarks/llm-judge-selection-latency.data.json').read_text())
    assert hashlib.sha256((root / data['chart']).read_bytes()).hexdigest() == data['chart_sha256']
    table = json.loads((BASE / 'dashboard_summary.json').read_text())['publication']['tables']['frontier_llm_judges'][:6]
    assert len(data['series']) == len(table) == 6
    for series, row in zip(data['series'], table):
        assert series['configuration_id'] == row['configuration_id']
        assert series['source_run'] == row['source_run']
        assert series['selection_p50_seconds'] == row['selection_p50_seconds']
        assert series['display_seconds'] == round(row['selection_p50_seconds'], 3)
