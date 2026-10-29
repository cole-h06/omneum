"""Verify active release documentation against frozen inputs and saved metrics."""
import json
from pathlib import Path
import re
from urllib.parse import unquote

import pytest

BASE = Path(__file__).resolve().parent
BENCHMARKS = BASE.parent
PAGES = (tuple(sorted(BENCHMARKS.glob('*.md'))) + (BASE / 'README.md',)
         + tuple(sorted((BASE / 'synthetic').glob('*.md')))
         + tuple(sorted((BASE / 'synthetic/contracts').rglob('*.md'))))


@pytest.mark.parametrize('page', PAGES, ids=lambda p: p.name)
def test_documentation_links(page):
    for target in re.findall(r'!?\[[^\]]*\]\(([^\s)]+)\)', page.read_text()):
        if target.startswith(('https:', 'http:', 'mailto:', '#')):
            continue
        path = (page.parent / unquote(target.split('#', 1)[0])).resolve()
        assert path.exists(), f'{page.name}: {target}'
        for part in path.parents:
            child = path.relative_to(part).parts[0]
            assert child in {p.name for p in part.iterdir()}, f'{page.name}: wrong filename case in {target}'


@pytest.mark.parametrize('heading,methods', [
    ('Semantic Rerankers', ('raw_budget', 'bm25', 'bm25_omneum', 'embedding', 'embedding_omneum',
                           'bge', 'bge_omneum', 'cohere', 'cohere_omneum', 'omneum')),
    ('Frontier LLM Judges', ('claude', 'gpt', 'gemini', 'omneum', 'bge_omneum', 'cohere_omneum'))])
def test_current_leaderboard_metrics(heading, methods):
    results = BASE / 'synthetic/results'
    values = json.loads((results / 'tier1-competitors-20261025-v1/summary.json').read_text())['aggregate']
    import csv
    values.update({row['method']: row for row in csv.DictReader(
        (results / 'budget-exhaustion-recovery-20261026-v2/aggregate.csv').open())})
    section = (BENCHMARKS / 'leaderboard.md').read_text().split(f'## {heading}\n', 1)[1].split('\n## ', 1)[0]
    displayed = []
    for line in section.splitlines():
        cells = [c.strip().replace('**', '') for c in line.strip('|').split('|')]
        if line.startswith('|') and len(cells) == 7 and '%' in cells[1]:
            displayed.append(cells)
    assert len(displayed) == len(methods)
    fields = ('source_precision', 'source_recall', 'evidence_retention',
              'supporting_passage_claim_coverage', 'independent_evidence_coverage')
    for cells, method in zip(displayed, methods):
        row = values[method]
        assert cells[1:6] == [f'{float(row[field]):.2%}' for field in fields]
        assert cells[6] == f"{float(row['tokenizer_tokens']):.2f}"


def test_documented_token_budgets_match_current_manifest():
    manifest = json.loads((BASE / 'synthetic/results/tier1-competitors-20261025-v1/manifest.json').read_text())
    declared = ', '.join(map(str, manifest['budgets']))
    for name in ('README.md', 'leaderboard.md'):
        assert declared + ' Qwen tokens' in (BENCHMARKS / name).read_text()


def test_current_docs_use_public_benchmark_name():
    for page in PAGES:
        assert not re.search(r'\bTier\s+1\b', page.read_text(), re.IGNORECASE), page
    assert 'Cross-Domain Context Curation Benchmark' in (BENCHMARKS / 'README.md').read_text()
