"""Verify exact already accepted artifacts; never build, upload, or replace files."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

SOURCE = '978bc5806a13bcdbcd40e0f5b6d0b284935c6517'
RUN = '38317382168'
MANIFEST_SHA256 = '76a4b387778b4e12c729321b89daba7b8827671109c10cad175f58253909ab33'


def main():
    run = json.loads(subprocess.check_output(['gh', 'run', 'view', RUN, '--repo', 'cole-h06/omneum',
                                            '--json', 'headSha,status,conclusion,jobs']))
    assert run['headSha'] == SOURCE and run['status'] == 'completed' and run['conclusion'] == 'success'
    assert sum(j['conclusion'] == 'success' for j in run['jobs']) == 44
    assert all(j['conclusion'] == 'success' or
               (j['conclusion'] == 'skipped' and j['name'] in
                ['Publish daemon GitHub Release', 'Publish validated wheels to PyPI']) for j in run['jobs'])
    path = Path('approved-manifest/release-manifest.json')
    assert hashlib.sha256(path.read_bytes()).hexdigest() == MANIFEST_SHA256
    manifest = json.loads(path.read_text())
    assert manifest['version'] == '1.0.4' and len(manifest['distributions']) == 17 and len(manifest['daemon_assets']) == 4
    folders = {'distributions': 'pypi-dist', 'daemon_assets': sys.argv[1] if len(sys.argv) > 1 else 'release-assets'}
    for kind, folder in folders.items():
        root = Path(folder)
        assert {f.name for f in root.iterdir()} == set(manifest[kind])
        for name, expected in manifest[kind].items():
            item = root / name
            assert item.is_file() and not item.is_symlink()
            assert item.stat().st_size == expected['size'], name
            assert hashlib.sha256(item.read_bytes()).hexdigest() == expected['sha256'], name
    print('PASS: approved source/run and all 21 original artifact bytes verified; no rebuild')


if __name__ == '__main__':
    main()
