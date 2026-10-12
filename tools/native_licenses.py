"""Reproduce native dependency notices from checksum-pinned Cargo archives."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'omneum/NATIVE-LICENSES.txt'
PREFIXES = ('LICENSE', 'LICENCE', 'COPYING', 'COPYRIGHT', 'NOTICE', 'UNLICENSE')


def generated():
    metadata = json.loads(subprocess.check_output(
        ['cargo', 'metadata', '--locked', '--all-features', '--format-version=1'], cwd=ROOT))
    nodes = {node['id']: node for node in metadata['resolve']['nodes']}
    pending, selected = [metadata['resolve']['root']], set()
    while pending:
        identifier = pending.pop()
        if identifier in selected:
            continue
        selected.add(identifier)
        for dependency in nodes[identifier]['deps']:
            if any(kind['kind'] != 'dev' for kind in dependency['dep_kinds']):
                pending.append(dependency['pkg'])
    locked = tomllib.loads((ROOT / 'Cargo.lock').read_text())
    checksums = {(p['name'], p['version']): p['checksum'] for p in locked['package'] if 'checksum' in p}
    parts = ['Omneum native dependency license notices\n',
             'Locked normal/build dependency union for SDK and daemon targets.\n'
             'Conditional/build dependencies may not be linked on every platform.\n'
             'Project and bundled MCP licenses are also distributed separately.\n'
             'License text line endings are normalized to LF for all build platforms.\n']
    for package in sorted(metadata['packages'], key=lambda p: (p['name'], p['version'])):
        if package['id'] not in selected or package['source'] is None:
            continue
        if not package['source'].startswith('registry+'):
            raise ValueError('unsupported native license source: ' + package['name'])
        source = Path(package['manifest_path']).parent
        registry = source.parent.name
        archive = source.parents[2] / 'cache' / registry / f"{package['name']}-{package['version']}.crate"
        data = archive.read_bytes()
        expected = checksums[(package['name'], package['version'])]
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError('Cargo archive checksum mismatch: ' + package['name'])
        prefix = f"{package['name']}-{package['version']}/"
        files = {}
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as tar:
            for member in tar:
                relative = member.name.removeprefix(prefix)
                if (member.isfile() and member.name.startswith(prefix) and '/' not in relative
                        and relative.upper().startswith(PREFIXES)):
                    files[relative] = tar.extractfile(member).read().decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')
        if not files:
            raise ValueError('native dependency lacks license text: ' + package['name'])
        parts.append(f"\n{'=' * 72}\n{package['name']} {package['version']}\n"
                     f"SPDX: {package['license']}\nCargo SHA-256: {expected}\n")
        for name, text in sorted(files.items()):
            parts.append(f'\n--- {name} ---\n{text.rstrip()}\n')
    # This source document was extracted from the exact pinned Rust toolchain.
    parts.append('\n' + (ROOT / 'omneum/RUST-STDLIB-LICENSES.txt').read_text())
    return ''.join(parts).encode('utf-8')


def verify_artifacts(paths):
    resources = ('omneum/NATIVE-LICENSES.txt', 'omneum/RUST-STDLIB-LICENSES.txt')
    for path in paths:
        if path.suffix == '.whl':
            with zipfile.ZipFile(path) as archive:
                for name in resources:
                    if archive.read(name) != (ROOT / name).read_bytes():
                        raise ValueError('packaged native license mismatch: ' + name)
                names = [n for n in archive.namelist() if n.endswith('.dist-info/licenses/LICENSE')]
                if len(names) != 1 or archive.read(names[0]) != (ROOT / 'LICENSE').read_bytes():
                    raise ValueError('packaged project license mismatch')
        else:
            with tarfile.open(path, 'r:gz') as archive:
                prefix = path.name.removesuffix('.tar.gz') + '/'
                for name in (*resources, 'LICENSE'):
                    if archive.extractfile(prefix + name).read() != (ROOT / name).read_bytes():
                        raise ValueError('packaged native license mismatch: ' + name)
        print('Verified packaged native licenses: ' + path.name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--artifacts', type=Path, nargs='+')
    args = parser.parse_args()
    if args.artifacts:
        verify_artifacts(args.artifacts)
        return
    content = generated()
    if args.check:
        if OUTPUT.read_bytes() != content:
            raise SystemExit('native notices differ from checksum-pinned Cargo sources')
    else:
        OUTPUT.write_bytes(content)
    print('Verified native license notices' if args.check else 'Generated native license notices')


if __name__ == '__main__':
    main()
