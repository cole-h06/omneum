"""Read-only registry and distribution checks; no third-party dependencies (Python 3.11+)."""
import argparse
import ast
import configparser
from email.parser import Parser
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile
import tomllib
from urllib.error import URLError
from urllib.request import urlopen
from urllib.parse import urlparse
import zipfile

ROOT = Path(__file__).resolve().parents[1]
IDENTITY = 'ai.omneum/omneum'
REPOSITORY = 'https://github.com/cole-h06/omneum'
MARKER = f'mcp-name: {IDENTITY}'
ENTRY_POINTS = {'omneum': 'omneum.cli:app', 'omneum-server': 'omneum.proxy:main',
                'omneum-contributor': 'omneum.contributor:main'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def ownership(description):
    require(re.search(re.escape(MARKER) + r'(?=\s|<|-->|$)', description),
            'missing exact PyPI ownership marker')


def check_source(root=ROOT):
    project = tomllib.loads((root / 'pyproject.toml').read_text())['project']
    manifest = json.loads((root / 'server.json').read_text())
    version = project['version']
    require(re.fullmatch(r'\d+\.\d+\.\d+', version), 'expected stable release version')
    require(project['name'] == 'omneum', 'wrong PyPI project name')
    require(manifest['name'] == IDENTITY, 'official identity changed')
    require(manifest['$schema'] == 'https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json', 'unexpected MCP schema')
    require(manifest['version'] == version, 'manifest version mismatch')
    require(manifest['repository'] == {'url': REPOSITORY, 'source': 'github'}, 'repository mismatch')
    require(project['urls']['Repository'] == REPOSITORY, 'project repository mismatch')
    require(project['urls']['Issues'] == REPOSITORY + '/issues', 'issues URL mismatch')
    require(manifest['websiteUrl'] == REPOSITORY + '/blob/main/docs/guides/installation.md', 'installation URL mismatch')
    require(project['readme'] == 'README.md', 'published-description source changed')
    ownership((root / project['readme']).read_text())
    require(project['scripts'] == ENTRY_POINTS, 'installation entry points changed')
    for name, target in ENTRY_POINTS.items():
        module, symbol = target.split(':')
        tree = ast.parse((root / (module.replace('.', '/') + '.py')).read_text())
        symbols = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
        symbols.update(t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name))
        require(symbol in symbols, f'{name}: entry point missing from source')
    versions = [tomllib.loads((root / 'Cargo.toml').read_text())['package']['version']]
    tree = ast.parse((root / 'omneum/__init__.py').read_text())
    versions += [ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '__version__' for t in n.targets)]
    require(len(versions) == 2 and all(v == version for v in versions), 'Rust/Python version mismatch')
    require(len(manifest['packages']) == 1, 'unexpected package count')
    package = manifest['packages'][0]
    require(package == {
        'registryType': 'pypi', 'registryBaseUrl': 'https://pypi.org', 'identifier': 'omneum',
        'version': version, 'transport': {'type': 'stdio'}, 'runtimeHint': 'uvx',
        'runtimeArguments': [{'type': 'named', 'name': '--from', 'value': f'omneum=={version}'},
                             {'type': 'positional', 'value': 'omneum-server'}]}, 'package identifier/version/launch mismatch')
    glama = json.loads((root / 'glama.json').read_text())
    require(glama == {'$schema': 'https://glama.ai/mcp/schemas/server.json', 'maintainers': ['cole-h06']}, 'Glama metadata mismatch')
    return version


def check_metadata(text, version):
    metadata = Parser().parsestr(text)
    require(metadata['Name'] == 'omneum', 'distribution name mismatch')
    require(metadata['Version'] == version, 'distribution version mismatch')
    require(metadata.get('Description-Content-Type', '').split(';')[0].strip() == 'text/markdown', 'description content type mismatch')
    require(f'Repository, {REPOSITORY}' in metadata.get_all('Project-URL', []), 'distribution repository mismatch')
    ownership(metadata.get_payload())


def check_artifact(data, filename, version):
    if filename.endswith('.whl'):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = [n for n in archive.namelist() if n.endswith('.dist-info/METADATA')]
            require(len(names) == 1, 'wheel must contain one METADATA')
            check_metadata(archive.read(names[0]).decode(), version)
            config = configparser.ConfigParser()
            config.read_string(archive.read(names[0].replace('METADATA', 'entry_points.txt')).decode())
            require(dict(config['console_scripts']) == ENTRY_POINTS, 'wheel entry points mismatch')
    elif filename.endswith('.tar.gz'):
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
            # Inspect without extracting or executing package code.
            names = [n for n in archive.getnames() if n.count('/') == 1 and n.endswith('/PKG-INFO')]
            require(len(names) == 1, 'sdist must contain one root PKG-INFO')
            check_metadata(archive.extractfile(names[0]).read().decode(), version)
            ownership(archive.extractfile(names[0].replace('PKG-INFO', 'README.md')).read().decode())
    else:
        raise ValueError('unsupported distribution format')


def fetch(url, limit=100 * 1024 * 1024):
    with urlopen(url, timeout=60) as response:
        data = response.read(limit + 1)
    require(len(data) <= limit, 'response exceeds size limit')
    return data


def check_pypi(document, version, downloader=fetch):
    info = document['info']
    require(info['name'] == 'omneum' and info['version'] == version, 'PyPI release identity/version mismatch')
    ownership(info['description'])
    require(info['project_urls']['Repository'] == REPOSITORY, 'PyPI repository mismatch')
    files = document['urls']
    require(files and all(not f['yanked'] for f in files), 'missing or yanked release files')
    for kind in ('bdist_wheel', 'sdist'):
        candidates = [f for f in files if f['packagetype'] == kind]
        require(candidates, f'PyPI release missing {kind}')
        artifact = sorted(candidates, key=lambda f: f['filename'])[0]
        url = urlparse(artifact['url'])
        require(url.scheme == 'https' and url.hostname == 'files.pythonhosted.org', 'untrusted PyPI artifact URL')
        data = downloader(artifact['url'])
        require(hashlib.sha256(data).hexdigest() == artifact['digests']['sha256'], 'PyPI artifact hash mismatch')
        check_artifact(data, artifact['filename'], version)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--artifacts', type=Path)
    parser.add_argument('--pypi', action='store_true', help='require public exact-version PyPI description, wheel and sdist')
    parser.add_argument('--version', help='require this version, e.g. workflow dispatch input')
    args = parser.parse_args()
    version = check_source(args.root)
    if args.version:
        require(args.version == version, 'requested version differs from source')
    if args.artifacts:
        files = sorted(args.artifacts.glob('*.whl')) + sorted(args.artifacts.glob('*.tar.gz'))
        require(any(p.suffix == '.whl' for p in files) and any(p.name.endswith('.tar.gz') for p in files), 'built wheel and sdist required')
        for path in files:
            check_artifact(path.read_bytes(), path.name, version)
    if args.pypi:
        check_pypi(json.loads(fetch(f'https://pypi.org/pypi/omneum/{version}/json')), version)
    print(f'Registry checks passed: {IDENTITY} {version}')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError, URLError) as error:
        raise SystemExit(f'Registry checks failed: {error}')
