"""Bounded, link-free Linux runtime format. Also shipped beside the root installer.

Only the enclosing SHA-256-verified release may supply this archive.
This module uses the standard library and supports Ubuntu's system Python 3.10.
"""
import gzip
import json
from pathlib import Path, PurePosixPath
import shutil
import tarfile

MAX_RUNTIME = 1024 * 1024 * 1024
MAX_MEMBERS = 50000
REQUIRED = {'.venv', '.venv/bin', '.venv/bin/python', '.venv/pyvenv.cfg', 'python', 'runtime.json'}


class BoundedReader:
    def __init__(self, stream):
        self.stream, self.total = stream, 0

    def read(self, size):
        data = self.stream.read(min(size, MAX_RUNTIME - self.total + 1))
        self.total += len(data)
        if self.total > MAX_RUNTIME:
            raise ValueError('runtime exceeds extraction limit')
        return data


def unpack(source, destination=None, version=None):
    """Validate a runtime, optionally extract it into a NEW private directory."""
    if destination is not None:
        destination = Path(destination)
        destination.mkdir(mode=0o700)
    seen, directories = set(), set()
    metadata = None
    with gzip.GzipFile(fileobj=source) as gz:
        with tarfile.open(fileobj=BoundedReader(gz), mode='r|') as archive:
            for member in archive:
                name = member.name
                path = PurePosixPath(name)
                if (len(seen) >= MAX_MEMBERS or name in seen or not name
                        or path.is_absolute() or '..' in path.parts or '\\' in name
                        or path.as_posix() != name
                        or path.parts[0] not in {'.venv', 'python', 'runtime.json'}
                        or (path.parts[0] == 'runtime.json' and name != 'runtime.json')
                        or member.pax_headers or member.linkname
                        or member.uid != 0 or member.gid != 0
                        or member.mode not in (0o644, 0o755)
                        or not (member.isdir() or member.isreg())
                        or not 0 <= member.size <= MAX_RUNTIME
                        or (member.isdir() and (member.size or member.mode != 0o755))
                        or (name in {'.venv/bin/python', '.venv/pyvenv.cfg'} and (not member.isreg() or not member.size))
                        or (name == '.venv/bin/python' and member.mode != 0o755)
                        or any(p.as_posix() not in directories for p in path.parents if p.as_posix() != '.')):
                    raise ValueError('invalid runtime archive member: ' + name)
                seen.add(name)
                if member.isdir():
                    directories.add(name)
                    if destination is not None:
                        (destination / name).mkdir(mode=0o755)
                        (destination / name).chmod(0o755)
                    continue
                with archive.extractfile(member) as contents:
                    if name == 'runtime.json':
                        if member.size > 4096:
                            raise ValueError('runtime metadata exceeds limit')
                        data = contents.read()
                        metadata = json.loads(data)
                        if destination is not None:
                            (destination / name).write_bytes(data)
                    elif destination is not None:
                        with (destination / name).open('xb') as output:
                            shutil.copyfileobj(contents, output, length=65536)
                    else:
                        while contents.read(65536):
                            pass
                if destination is not None:
                    (destination / name).chmod(member.mode)
    if not REQUIRED <= seen or metadata != {'format': 1, 'version': version, 'prefix': '/opt/omneum'}:
        raise ValueError('incomplete runtime or package version mismatch')
    if not {'.venv', '.venv/bin', 'python'} <= directories or '.venv/bin/python' in directories:
        raise ValueError('invalid runtime layout')
    return metadata
