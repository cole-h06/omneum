"""Read-only PyPI preflight and exact publication verification; never upload/delete."""
import argparse
from email.parser import Parser
import hashlib
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.request import urlopen
import zipfile

import release_daemon
import release_sdist
import release_wheels


def fetch(version):
    try:
        with urlopen(f'https://pypi.org/pypi/omneum/{version}/json', timeout=30) as response:
            return json.load(response)
    except HTTPError as error:
        if error.code == 404:
            return None
        raise


def check_new(version, fetcher=fetch):
    if fetcher(version) is not None:
        raise ValueError(f'omneum {version} already exists on PyPI; never overwrite/delete or blindly retry')
    # Public 404 cannot reveal deleted filename tombstones. Owners must also
    # choose a never-used version, informed by their PyPI project history.
    print(f'PyPI {version}: absent from public index; owner must confirm version was never used/deleted')


def manifest(dist, assets, version):
    wheels = sorted(dist.glob('*.whl'))
    expected = {(python, platform) for python in release_wheels.PYTHONS for platform in release_wheels.PLATFORMS}
    targets = [release_wheels.inspect_wheel(path, version) for path in wheels]
    if len(targets) != len(expected) or set(targets) != expected:
        raise ValueError('publication requires the complete 16-wheel matrix')
    source = dist / f'omneum-{version}.tar.gz'
    release_sdist.verify(source, version)
    files = wheels + [source]
    if set(dist.iterdir()) != set(files):
        raise ValueError('unexpected publication file')
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as archive:
            metadata = Parser().parsestr(archive.read(f'omneum-{version}.dist-info/METADATA').decode())
            if 'mcp-name: ai.omneum/omneum' not in metadata.get_payload():
                raise ValueError('published description must include verified MCP identity')
    release_daemon.verify(assets, version)
    def entries(paths):
        return {path.name: {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'size': path.stat().st_size}
                for path in paths}
    return {'version': version, 'distributions': entries(files), 'daemon_assets': entries(sorted(assets.iterdir()))}


def verify_document(document, expected):
    if document is None or document['info']['version'] != expected['version']:
        raise ValueError('public release is not available at the exact version')
    actual = {item['filename']: item for item in document['urls']}
    if len(actual) != len(document['urls']) or set(actual) != set(expected['distributions']):
        raise ValueError('public distribution set is incomplete or unexpected')
    if 'mcp-name: ai.omneum/omneum' not in document['info']['description']:
        raise ValueError('public description is missing MCP verification identity')
    for name, recorded in expected['distributions'].items():
        item = actual[name]
        if item['yanked'] or item['digests']['sha256'] != recorded['sha256'] or item['size'] != recorded['size']:
            raise ValueError(f'public distribution mismatch: {name}')
    return actual


def verify_public(expected, attempts, delay):
    for attempt in range(attempts):
        try:
            actual = verify_document(fetch(expected['version']), expected)
            for name, item in actual.items():
                with urlopen(item['url'], timeout=60) as response:
                    digest = hashlib.sha256(response.read()).hexdigest()
                if digest != expected['distributions'][name]['sha256']:
                    raise ValueError(f'anonymous downloaded bytes mismatch: {name}')
            print(f'PASS: all {len(actual)} public distributions match approved bytes')
            return
        except (ValueError, HTTPError, TimeoutError) as error:
            if attempt + 1 == attempts:
                raise
            print(f'Public verification pending ({attempt + 1}/{attempts}): {error}')
            time.sleep(delay)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['check-new', 'manifest', 'verify-public'])
    parser.add_argument('--version', required=True)
    parser.add_argument('--dist', type=Path, default=Path('pypi-dist'))
    parser.add_argument('--daemon-assets', type=Path, default=Path('release-assets'))
    parser.add_argument('--manifest', type=Path, default=Path('release-manifest.json'))
    parser.add_argument('--attempts', type=int, default=12)
    parser.add_argument('--delay', type=int, default=10)
    args = parser.parse_args()
    if args.command == 'check-new':
        check_new(args.version)
    elif args.command == 'manifest':
        args.manifest.write_text(json.dumps(manifest(args.dist, args.daemon_assets, args.version), indent=2) + '\n')
    else:
        expected = json.loads(args.manifest.read_text())
        if expected['version'] != args.version or args.attempts < 1 or args.delay < 0:
            raise ValueError('invalid publication verification arguments')
        verify_public(expected, args.attempts, args.delay)


if __name__ == '__main__':
    main()
