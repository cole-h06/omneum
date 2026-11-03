"""Check directory descriptions and supplied PR #2 metadata without duplicating it."""
import argparse
import json
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def check(glama):
    listing = json.loads((ROOT / 'docs/discovery/listing.json').read_text())
    manifest = json.loads((ROOT / 'deploy/discovery/mcpb/manifest.json').read_text())
    version = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']
    assert listing['version'] == manifest['version'] == version
    assert listing['repository'] == 'https://github.com/cole-h06/omneum'
    assert listing['command'] == 'omneum-server' and listing['transport'] == 'stdio'
    assert listing['setup'] == ['python -m pip install omneum', 'omneum install']
    assert not listing['one_click_installation'] and not listing['windows_local_server']
    entry = (ROOT / 'docs/discovery/submissions/awesome-entry.md').read_text()
    assert entry.count('\n') == 1 and '[cole-h06/omneum]' in entry
    assert '🏠' in entry and '🍎' in entry and '🐧' in entry and '🪟' not in entry
    assert 'pip install omneum' in entry and 'omneum install' in entry
    assert '/badges/score.svg' in entry
    if glama:
        data = json.loads(glama.read_text())
        assert data == {'$schema': 'https://glama.ai/mcp/schemas/server.json', 'maintainers': ['cole-h06']}
    print('Discovery consistency checks passed' + ('; supplied Glama metadata checked' if glama else '; PR #2 Glama file not supplied'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--glama-json', type=Path)
    check(parser.parse_args().glama_json)
