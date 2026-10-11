import io
import base64
import csv
import hashlib
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


def test_runtime_metadata_is_portable_and_record_matches(tmp_path):
    root = tmp_path / 'root'; fixture(root)
    site = root / '.venv/lib/python3.13/site-packages'
    info = site / 'omneum-1.0.3.dist-info'
    (info / 'sboms').mkdir(parents=True)
    (info / 'direct_url.json').write_text('{"url":"file:///home/runner/work/omneum"}')
    (info / 'sboms/cargo.json').write_text('{"ref":"path+file:///home/runner/work/omneum#omneum_oprf@1.0.3"}')
    (info / 'RECORD').write_text('omneum-1.0.3.dist-info/direct_url.json,,\n'
        'omneum-1.0.3.dist-info/sboms/cargo.json,,\n'
        'omneum-1.0.3.dist-info/RECORD,,\n')
    output = tmp_path / 'runtime.tar.gz'
    build(root, output, '1.0.3')
    with tarfile.open(output) as archive:
        prefix = '.venv/lib/python3.13/site-packages/'
        assert prefix + 'omneum-1.0.3.dist-info/direct_url.json' not in archive.getnames()
        record = archive.extractfile(prefix + 'omneum-1.0.3.dist-info/RECORD').read().decode()
        rows = list(csv.reader(io.StringIO(record)))
        assert len(rows) == 2
        data = archive.extractfile(prefix + rows[0][0]).read()
        assert json.loads(data) == {'ref': 'pkg:cargo/omneum_oprf@1.0.3'}
        expected = 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()
        assert rows[0][1:] == [expected, str(len(data))]
    assert (info / 'direct_url.json').exists()  # Build inputs are preserved.


def test_runtime_rejects_unremapped_native_paths_before_packaging(tmp_path):
    root = tmp_path / 'root'; fixture(root)
    native = root / '.venv/lib/python3.13/site-packages/omneum_oprf/native.so'
    native.parent.mkdir(parents=True)
    native.write_bytes(b'native build /home/runner/work/omneum')
    output = tmp_path / 'runtime.tar.gz'
    with pytest.raises(ValueError, match='unremapped runtime native'):
        build(root, output, '1.0.3')
    assert not output.exists()
