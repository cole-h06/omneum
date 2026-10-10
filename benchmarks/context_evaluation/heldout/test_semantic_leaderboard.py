"""Offline figure integrity and rendering contract."""
from copy import deepcopy
import hashlib
import json
import xml.etree.ElementTree as ET

import pytest
from PIL import Image

from .build_dashboard_summary import OUTPUT, ROOT
from .render_semantic_leaderboard import (
    COLORS, WIDTH, HEIGHT, SCALE, publication_rows, make_scene, render, generate, verified_scope,
)


@pytest.fixture
def data():
    return json.loads(OUTPUT.read_text())


def test_displayed_values_and_cost_boundary(data):
    rows = publication_rows(data)
    assert [r['tokens'] for r in rows] == [11941, 11595, 11577, 11535]
    assert [r['cost'] for r in rows] == pytest.approx([.074618, .070662, .071242, .070654])
    assert [r['accuracy'] for r in rows] == pytest.approx([22/24, 21/24, 21/24, 19/24])
    assert [r['selection_p50_seconds']*1000 for r in rows] == pytest.approx([200.736312, 660.201396, 151.160417, 624.052771])
    for baseline, augmented in zip(rows[::2], rows[1::2]):
        assert augmented['accuracy'] < baseline['accuracy']
        assert augmented['selection_p50_seconds'] > baseline['selection_p50_seconds']
    assert rows[2]['tokens'] is not None
    assert data['configurations'][2]['api_tokens']['total']['total'] is None


def test_scope_and_neutral_badges(data):
    scope = verified_scope()
    assert scope['cases'] == 24
    assert scope['domains'] == ['coding_agents', 'data_analytics_agents', 'enterprise_rag',
                               'multi_agent_systems', 'research_analysis_agents', 'support_operations_agents']
    assert len(scope['environments']) == 6  # Explicit matrix labels, counted independently.
    scene = make_scene(publication_rows(data))
    texts = [i[3] for i in scene.items if i[0] == 'text']
    assert '24 Held-out Cases' in texts and '6 Domains' in texts
    badges = [i for i in scene.items if i[0] == 'rect' and i[2] == 30]
    assert len(badges) == 2 and all(i[5] == '#F0F3F5' for i in badges)


@pytest.mark.parametrize('mutation', ['missing', 'units', 'pair', 'basis', 'tokens', 'cost', 'macro'])
def test_reject_inconsistent_sources(data, mutation):
    d = deepcopy(data)
    table = d['publication']['tables']['semantic_rerankers']
    if mutation == 'missing': table[0]['precision'] = None
    elif mutation == 'units': d['units']['latency'] = 'milliseconds'
    elif mutation == 'pair': table.reverse()
    elif mutation == 'basis': table[0]['accuracy_basis'] = 'manual semantic'
    elif mutation == 'tokens': d['configurations'][0]['api_tokens']['generation']['total'] = 0
    elif mutation == 'cost': d['configurations'][0]['cost_usd']['generation'] = 0
    elif mutation == 'macro': table[0]['precision'] = .5
    with pytest.raises(ValueError): publication_rows(d)


def test_precision_bars_share_zero_to_one_hundred_scale(data):
    rows = publication_rows(data)
    scene = make_scene(rows)
    bars = [i for i in scene.items if i[0] == 'rect' and i[1] == 515 and i[4] == 13 and i[5] != '#EAF0F4']
    assert [b[3] for b in bars] == pytest.approx([204 * r['precision'] for r in rows])
    assert [b[5] for b in bars] == [r['color'] for r in rows]
    assert COLORS['omneum'] in (ROOT/'assets/omneum-logotype.svg').read_text()


def test_shared_vector_and_raster_scene_is_deterministic(data):
    scene = make_scene(publication_rows(data))
    svg, png = render(scene)
    second_svg, second_png = render(scene)
    assert svg == second_svg and png.tobytes() == second_png.tobytes()
    tree = ET.fromstring(svg)
    assert tree.attrib['viewBox'] == f'0 0 {WIDTH} {HEIGHT}'
    assert png.size == (WIDTH*SCALE, HEIGHT*SCALE)
    texts = [e.text or '' for e in tree.findall('{http://www.w3.org/2000/svg}text')]
    assert texts == [i[3] for i in scene.items if i[0] == 'text']
    assert not tree.findall('.//{http://www.w3.org/2000/svg}image')


def test_checked_in_exports_and_rebuild(tmp_path):
    generate(tmp_path)
    for name in ['semantic-rerankers.svg', 'semantic-rerankers.png']:
        assert (tmp_path/name).read_bytes() == (ROOT/'assets/benchmarks'/name).read_bytes()
    with Image.open(tmp_path/'semantic-rerankers.png') as im:
        assert im.info['SVG SHA256'] == hashlib.sha256((tmp_path/'semantic-rerankers.svg').read_bytes()).hexdigest()
