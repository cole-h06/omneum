"""Package CI's non-editable runtime for installation at /opt/omneum."""
import argparse
import base64
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
import posixpath
import re
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'omneum'))
from runtime_bundle import unpack


def portable_metadata(entries, version):
    """Remove installation-local origin paths and repair installed RECORD hashes."""
    overrides = {}
    marker = '/omneum-' + version + '.dist-info/'
    def normalize(value):
        if isinstance(value, dict):
            return {key: normalize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if isinstance(value, str):
            return re.sub(r'path\+file://[^#]+#([^" ]+)', r'pkg:cargo/\1', value)
        return value
    for name, source in list(entries.items()):
        if marker in name and name.endswith('/direct_url.json'):
            del entries[name]  # The local build location is not a public origin.
        elif marker in name and '/sboms/' in name and name.endswith('.json'):
            overrides[name] = (json.dumps(normalize(json.loads(source.read_bytes())), sort_keys=True) + '\n').encode()
        elif '/site-packages/omneum_oprf/' in name and source.is_file():
            if re.search(rb'/Users/|/home/runner/', source.read_bytes()):
                raise ValueError('unremapped runtime native build path')
    for name, source in entries.items():
        if marker not in name or not name.endswith('/RECORD'):
            continue
        prefix = name.rsplit('/', 2)[0] + '/'
        rows = []
        for row in csv.reader(io.StringIO(source.read_text())):
            target = posixpath.normpath(prefix + row[0])
            if row[0] == 'omneum-' + version + '.dist-info/direct_url.json':
                continue
            if target in overrides:
                data = overrides[target]
                row = [row[0], 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode(), str(len(data))]
            rows.append(row)
        output = io.StringIO(newline='')
        csv.writer(output, lineterminator='\n').writerows(rows)
        overrides[name] = output.getvalue().encode()
    return overrides


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
    overrides = portable_metadata(entries, version)
    with output.open('wb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode='w', format=tarfile.GNU_FORMAT) as archive:
            for name, source in sorted(entries.items()):
                info = tarfile.TarInfo(name)
                info.mode = 0o755 if source.is_dir() or source.stat().st_mode & 0o111 else 0o644
                if source.is_dir():
                    info.type = tarfile.DIRTYPE
                    archive.addfile(info)
                else:
                    if name in overrides:
                        data = overrides[name]
                        info.size = len(data)
                        archive.addfile(info, io.BytesIO(data))
                        continue
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
