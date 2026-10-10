"""Verify active release documentation against frozen inputs and saved metrics."""
import json
from pathlib import Path
import re
from urllib.parse import unquote

import pytest

BASE = Path(__file__).resolve().parent
BENCHMARKS = BASE.parent
PAGES = tuple(sorted(BENCHMARKS.glob('*.md'))) + (BASE / 'README.md',)


@pytest.mark.parametrize('page', PAGES, ids=lambda p: p.name)
def test_active_relative_links_use_existing_case_sensitive_paths(page):
    for target in re.findall(r'!?\[[^\]]*\]\(([^\s)]+)\)', page.read_text()):
        if target.startswith(('https:', 'http:', 'mailto:', '#')):
            continue
        path = (page.parent / unquote(target.split('#', 1)[0])).resolve()
        assert path.exists(), f'{page.name}: {target}'
        for part in path.parents:
            child = path.relative_to(part).parts[0]
            assert child in {p.name for p in part.iterdir()}, f'{page.name}: wrong filename case in {target}'


@pytest.mark.parametrize('heading,family', [('Semantic Rerankers', 'semantic_rerankers'),
                                           ('Frontier LLM Judges', 'frontier_llm_judges')])
def test_leaderboard_numbers_use_declared_recorded_scores_and_matched_runs(heading, family):
    data = json.loads((BASE / 'heldout/dashboard_summary.json').read_text())
    configs = {c['id']: c for c in data['configurations']}
    section = (BENCHMARKS / 'leaderboard.md').read_text().split(f'## {heading}\n', 1)[1].split('\n## ', 1)[0]
    assert ('Recorded Answer Score' if family == 'semantic_rerankers' else 'Adjudicated Answer Accuracy') in section
    displayed = []
    for line in section.splitlines():
        cells = [c.strip().replace('**', '') for c in line.strip('|').split('|')]
        if line.startswith('|') and len(cells) == 8 and '%' in cells[1]:
            displayed.append(cells)
    rows = data['publication']['tables'][family]
    if family == 'frontier_llm_judges':
        rows = [r for r in rows if configs[r['configuration_id']]['method_id'].startswith('bge')]
    assert len(displayed) == len(rows)
    for cells, row in zip(displayed, rows):
        config = configs[row['configuration_id']]
        assert row['source_run'] == config['run_id']
        assert cells[1:4] == [f'{value:.2%}' for value in
                             (row['precision'], row['recall'], config['recorded_answer_scores']['accuracy']
                              if family == 'semantic_rerankers' else row['accuracy'])]
        for cell, key in zip(cells[4:6], ('selection_p50_seconds', 'end_to_end_p50_seconds')):
            match = re.fullmatch(r'(\d+(?:\.\d+)?)(ms|s)', cell)
            assert match, cell
            number, unit = match.groups()
            decimals = len(number.split('.')[1]) if '.' in number else 0
            assert float(number) == round(row[key] * (1000 if unit == 'ms' else 1), decimals)
        assert int(cells[6].replace(',', '')) == config['api_tokens']['generation']['total']
        assert float(cells[7].removeprefix('$')) == pytest.approx(config['cost_usd']['generation'], abs=0.0000005)


def test_documented_dataset_budget_matches_case_files():
    cases = [json.loads(p.read_text()) for p in (BASE / 'heldout/cases').glob('*/case.json')]
    budgets = [case['context_budget'] for case in cases]
    assert len(cases) == 24
    declared = f'{min(budgets)}–{max(budgets)}'
    for name in ('README.md', 'leaderboard.md'):
        assert f'| {"Selection budget" if name == "README.md" else "Context budget"} | {declared}' in (BENCHMARKS / name).read_text()
