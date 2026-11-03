"""Build an allow-listed MCPB connector reproducibly; never publish or install."""
import argparse
import hashlib
import json
from pathlib import Path
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = {'manifest.json': 'deploy/discovery/mcpb/manifest.json',
         'server/launch.cjs': 'deploy/discovery/mcpb/server/launch.cjs',
         'README.md': 'deploy/discovery/mcpb/README.md', 'LICENSE': 'LICENSE'}


def build(output):
    manifest = json.loads((ROOT / FILES['manifest.json']).read_text())
    version = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']
    if manifest['version'] != version:
        raise ValueError('MCPB/package version mismatch')
    output.mkdir(parents=True, exist_ok=True)
    target = output / f'omneum-local-{version}.mcpb'
    if target.exists():
        raise FileExistsError('refusing to overwrite an existing bundle')
    with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, source in sorted(FILES.items()):
            entry = zipfile.ZipInfo(name, date_time=(2025, 1, 1, 0, 0, 0))
            entry.external_attr = 0o100644 << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, (ROOT / source).read_bytes())
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    (output / f'{target.name}.sha256').write_text(f'{digest}  {target.name}\n')
    print(f'{target}\nSHA256 {digest}')
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/discovery')
    build(parser.parse_args().output)
