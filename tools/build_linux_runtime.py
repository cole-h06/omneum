"""Freeze CI's non-editable /opt/omneum environment into a relocatable-at-fixed-prefix archive."""
import argparse
import gzip
import io
import json
from pathlib import Path
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'omneum'))
from runtime_bundle import unpack


def build(root, output, version):
    root = root.resolve()
    # Dereference only links into the managed tree. Never ship links or host files.
    entries = {}
    for name in ('.venv', 'python'):
        def visit(path, relative, ancestors):
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(root) or resolved in ancestors:
                raise ValueError('external or cyclic runtime link: ' + str(path))
            if '__pycache__' in relative.parts or relative.suffix == '.pyc':
                return
            entries[relative.as_posix()] = resolved
            if resolved.is_dir():
                for child in sorted(resolved.iterdir()):
                    visit(child, relative / child.name, ancestors | {resolved})
            elif not resolved.is_file():
                raise ValueError('unsupported runtime file: ' + str(path))
        visit(root / name, Path(name), set())
    # Materializing venv interpreter symlinks changes $ORIGIN for the ELF loader.
    # Supply its managed libpython beside the copied venv executables as well.
    interpreter = (root / '.venv/bin/python').resolve(strict=True)
    for library in (interpreter.parent.parent / 'lib').glob('libpython*.so*'):
        resolved = library.resolve(strict=True)
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise ValueError('external libpython dependency')
        entries['.venv/lib/' + library.name] = resolved
    with output.open('wb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode='w', format=tarfile.GNU_FORMAT) as archive:
            for name, source in sorted(entries.items()):
                info = tarfile.TarInfo(name)
                info.mode = 0o755 if source.is_dir() or source.stat().st_mode & 0o111 else 0o644
                if source.is_dir():
                    info.type = tarfile.DIRTYPE
                    archive.addfile(info)
                else:
                    info.size = source.stat().st_size
                    with source.open('rb') as contents:
                        archive.addfile(info, contents)
            metadata = json.dumps({'format': 1, 'version': version, 'prefix': '/opt/omneum'}, sort_keys=True).encode()
            info = tarfile.TarInfo('runtime.json')
            info.mode, info.size = 0o644, len(metadata)
            archive.addfile(info, io.BytesIO(metadata))
    with output.open('rb') as source:
        unpack(source, version=version)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/opt/omneum'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    build(args.root, args.output, args.version)
