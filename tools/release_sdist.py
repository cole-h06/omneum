"""Validate the source distribution before it is published alongside tested wheels."""
import argparse
from email.parser import Parser
from pathlib import Path, PurePosixPath
import tarfile
import tomllib


def verify(path, version):
    if path.is_symlink() or not path.is_file() or path.name != f'omneum-{version}.tar.gz':
        raise ValueError('source distribution name/version mismatch')
    prefix = f'omneum-{version}'
    with tarfile.open(path, 'r:gz') as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)):
            raise ValueError('duplicate source distribution member')
        for member in members:
            parts = PurePosixPath(member.name).parts
            if not parts or parts[0] != prefix or '..' in parts or not (member.isfile() or member.isdir()):
                raise ValueError('unsafe source distribution member')
            relative = '/'.join(parts[1:])
            if (relative.startswith(('tools/provenance_explorer/', 'docs/reviews/', 'src/__fuzz__/'))
                    or relative.endswith(('.pem', '.key', '.zip')) or any(part == '.env' or part.startswith('.env.') for part in parts)
                    or relative in ('evaluate.py', 'deploy/network/vm/production-audit.py')):
                raise ValueError('private or unrelated source distribution member')
        def read(name):
            return archive.extractfile(f'{prefix}/{name}').read()
        metadata = Parser().parsestr(read('PKG-INFO').decode())
        project = tomllib.loads(read('pyproject.toml').decode())
        cargo = tomllib.loads(read('Cargo.toml').decode())
        if (metadata.get_all('Name') != ['omneum'] or metadata.get_all('Version') != [version]
                or project['project']['version'] != version or cargo['package']['version'] != version):
            raise ValueError('source distribution metadata version mismatch')
        for required in ('omneum/NATIVE-LICENSES.txt', 'omneum/RUST-STDLIB-LICENSES.txt', 'omneum/mcp/LICENSE', 'omneum/mcp/UPSTREAM.json', 'omneum/mcp/types.py',
                         'omneum/mcp/server/stdio.py', 'omneum/mcp/client/stdio/__init__.py',
                         'Cargo.lock', 'src/lib.rs', 'omneum/cli.py', 'omneum/installation.py',
                         'omneum/algorithm_compatibility.json', 'omneum/schemas/research-event-v1.schema.json', 'LICENSE'):
            if not read(required):
                raise ValueError('empty required source distribution member')
    return version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdist', type=Path, required=True)
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    print('Source distribution verified:', verify(args.sdist, args.version))


if __name__ == '__main__':
    main()
