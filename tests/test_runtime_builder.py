import io
import json
from pathlib import Path
import runpy
import tarfile

import pytest

from omneum.runtime_bundle import unpack

build = runpy.run_path(Path(__file__).resolve().parents[1] / 'tools/build_linux_runtime.py')['build']


def fixture(root):
    for directory in ('.venv/bin', '.venv/lib', 'python/cpython/bin', 'python/cpython/lib'):
        (root / directory).mkdir(parents=True, exist_ok=True)
    (root / 'python/cpython/bin/python3.13').write_bytes(b'interpreter')
    (root / 'python/cpython/bin/python3.13').chmod(0o755)
    (root / 'python/cpython/lib/libpython3.13.so').write_bytes(b'library')
    (root / '.venv/bin/python').symlink_to(root / 'python/cpython/bin/python3.13')
    (root / '.venv/pyvenv.cfg').write_text('home = /opt/omneum/python/cpython/bin\n')


def test_materializes_runtime_and_libpython(tmp_path):
    root = tmp_path / 'root'; fixture(root)
    output = tmp_path / 'runtime.tar.gz'
    build(root, output, '1.0.3')
    with output.open('rb') as source:
        unpack(source, tmp_path / 'extracted', '1.0.3')
    assert (tmp_path / 'extracted/.venv/bin/python').read_bytes() == b'interpreter'
    assert (tmp_path / 'extracted/.venv/lib/libpython3.13.so').read_bytes() == b'library'
    assert not any(p.is_symlink() for p in (tmp_path / 'extracted').rglob('*'))
    again = tmp_path / 'again.tar.gz'; build(root, again, '1.0.3')
    assert again.read_bytes() == output.read_bytes()


@pytest.mark.parametrize('kind', ['external', 'cycle'])
def test_rejects_external_and_cyclic_links(tmp_path, kind):
    root = tmp_path / 'root'; fixture(root)
    (root / '.venv/bad').symlink_to('/etc/passwd' if kind == 'external' else root / '.venv')
    with pytest.raises(ValueError):
        build(root, tmp_path / 'runtime.tar.gz', '1.0.3')
