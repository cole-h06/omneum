"""Read-only operator audit; prints public configuration and metadata only."""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

from omneum import network_deploy as deploy

MANIFEST = 'da83ab8b4f47030dae7393987ed963f1d5015cd5705f4c8e6b37c2f3924578cc'
REVIEWED_FILES = {
    'network_deploy.py': 'b0521be6eba37993421af4350a0fc0cb65c32b294546645069d6545c9e996fda',
    'network_release.py': '4b91e387db371b5d129a48fd206ed0bd363751d63cdf2870b2f712097a54d812',
    'contribution/network.py': '0b3e4789ad984ee85758a9b056d83e13e6b5a05c67fdd898085e3f526044bbfe',
    'onboarding.py': 'ff04b6a7598cd92fae9602d4d8aa13d2c5e12a3b58beeb9d931e78170ff57b5c',
}


def metadata(path):
    path = Path(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        print('ABSENT', path)
        return
    print('FILE', path, 'uid=' + str(info.st_uid), 'gid=' + str(info.st_gid),
          'mode=' + oct(stat.S_IMODE(info.st_mode)), 'bytes=' + str(info.st_size))


def main():
    if os.geteuid() != 0:
        raise ValueError('run this read-only audit as root')
    artifacts = Path('/root/artifacts')
    deploy.safe_path(artifacts, directory=True)
    manifest = artifacts / 'SHA256SUMS'
    deploy.safe_path(manifest)
    if hashlib.sha256(manifest.read_bytes()).hexdigest() != MANIFEST:
        raise ValueError('artifact manifest authentication FAILED; stop deployment')
    print('PASS authenticated artifact manifest', MANIFEST)
    entries = []
    for line in manifest.read_text().splitlines():
        digest, name = line.split('  ', 1)
        if len(digest) != 64 or Path(name).name != name:
            raise ValueError('invalid artifact manifest entry')
        target = artifacts / name
        deploy.safe_path(target)
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError('artifact checksum FAILED; stop deployment')
        entries.append(name)
    print('PASS artifact checksums; files=' + str(len(entries)))
    info = json.loads((artifacts / 'build-info.json').read_text())
    for key in ('python', 'machine', 'revision', 'diff_sha256', 'rust'):
        print('BUILD', key, info.get(key))
    if not (str(info.get('revision', '')).startswith('567cb0d')
            and str(info.get('python', '')).startswith('3.12.')
            and info.get('machine') == 'x86_64' and info.get('rust') == '1.90.0'):
        raise ValueError('build snapshot/platform/toolchain does not match approved deployment')
    runtime = Path(deploy.__file__).parent
    for name, expected in REVIEWED_FILES.items():
        source = Path('/root/repository/omneum') / name
        deploy.safe_path(source)
        for label, target in (('source', source), ('runtime', runtime / name)):
            if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
                raise ValueError('reviewed ' + label + ' module checksum FAILED: ' + name)
    print('PASS four reviewed source/runtime module checksums')
    if (artifacts / 'omneumd').read_bytes() != Path('/opt/omneum-network/libexec/omneumd').read_bytes():
        raise ValueError('installed evaluator differs from authenticated artifact')
    print('PASS installed evaluator matches artifact')
    deploy.validate_runtime_tree()
    deploy.identities()
    print('PASS runtime ownership and service identities')
    config = Path('/etc/omneum-network/production.json')
    c = json.loads(deploy.private_read(config))
    print('CONFIG fields match template:', set(c) == deploy.FIELDS)
    valid = False
    try:
        deploy.validate_config(c)
        valid = True
        print('PASS production configuration values')
    except Exception:
        print('BLOCKED production configuration incomplete or invalid')
    # Do not echo malformed settings, which could contain a mistakenly pasted
    # DSN or token. Valid production.json fields contain public values/paths.
    for key in sorted(deploy.FIELDS):
        if valid:
            print('PUBLIC', key, json.dumps(c[key]))
        else:
            print('SETTING', key, 'PRESENT (value suppressed)' if c.get(key) else 'MISSING')
    for path in ('/root/network-admin.dsn', '/root/omneum-setup/verified-database-ca.pem',
                 '/etc/omneum-network/secrets', '/var/lib/omneum-network-crypto/voprf.key',
                 '/etc/nginx/conf.d/omneum-acme.conf', '/etc/nginx/conf.d/omneum-network.conf',
                 '/etc/nginx/sites-available/omneum-network',
                 '/etc/letsencrypt/renewal/api.omneum.ai.conf'):
        metadata(path)
    for key in deploy.PATHS:
        if valid:
            metadata(c[key])
    for parent in ('/root/omneum-setup', '/etc/omneum-network/secrets'):
        if Path(parent).is_dir():
            print('FILENAMES', parent, json.dumps(sorted(p.name for p in Path(parent).iterdir())))
    result = subprocess.run(['nginx', '-t'], capture_output=True)
    print('Nginx syntax:', 'PASS' if result.returncode == 0 else 'FAIL')
    print('DONE read-only audit; no database connection or production changes')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Unexpected dependency errors can contain secrets; do not echo them.
        message = str(error) if type(error) is ValueError else 'audit dependency failed; inspect locally'
        sys.exit('FAIL: ' + message)
