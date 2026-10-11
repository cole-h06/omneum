"""Build an unpublished, statically linked Intel dependency wheel on macOS.

This does not make the wheel available to plain PyPI installs. Distribution
requires a separate decision; never replace the dependency with a vulnerable cap.
Run with Intel CPython 3.11 in a disposable build venv containing maturin 1.15.0,
cffi 2.0.0 and setuptools 82.0.1. Rust and Xcode command-line tools are build-only.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

from release_wheels import sanitize


SOURCES = {
    'cryptography-50.0.2': (
        'https://files.pythonhosted.org/packages/9d/af/182eb91b0df3fe75c4d9f26fe70684569566745f6ba7e5c9c73a862c5252/cryptography-50.0.2.tar.gz',
        '7b46165bb56eb4704e2eaaf86f3c940d19154535d9b0ca7d6d590b04060e00d5'),
    'openssl-3.5.9': (
        'https://github.com/openssl/openssl/releases/download/openssl-3.5.9/openssl-3.5.9.tar.gz',
        '603f5602e2eef00d77fbd429d34dcd5822bb301757a1bc9cdb24c670f1eb859a'),
}


def build_environment(work):
    environment = os.environ.copy()
    # PEP 517's no-isolation backend shells out to maturin. Selecting the venv
    # interpreter alone does not place that venv's console scripts on PATH.
    environment['PATH'] = str(Path(sys.executable).parent) + os.pathsep + environment['PATH']
    environment.update(CC='clang -arch x86_64', MACOSX_DEPLOYMENT_TARGET='10.13',
                       CARGO_BUILD_TARGET='x86_64-apple-darwin',
                       OPENSSL_STATIC='1',
                       OPENSSL_DIR=str(work / 'openssl-staging/opt/omneum-dependency/openssl'),
                       RUSTFLAGS=f'--remap-path-prefix={work}=/build/intel-dependency '
                                 f'--remap-path-prefix={Path.home()}=/build/user')
    return environment


def build(work, output):
    if sys.platform != 'darwin' or sys.version_info[:2] != (3, 11):
        raise ValueError('use Intel macOS CPython 3.11 for the abi3 build')
    import platform
    if platform.machine() != 'x86_64':
        raise ValueError('build interpreter must be Intel (Rosetta is supported)')
    if output.exists():
        raise ValueError('output must be new')
    if work.exists():
        raise ValueError('work directory must be new; never reuse modified sources')
    work.mkdir(parents=True)
    for name, (url, digest) in SOURCES.items():
        archive = work / (name + '.tar.gz')
        with urllib.request.urlopen(url, timeout=60) as response:
            archive.write_bytes(response.read())
        if hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
            raise ValueError('source checksum mismatch: ' + name)
        with tarfile.open(archive) as source:
            source.extractall(work, filter='data')
    environment = build_environment(work)
    def run(*args, cwd=work):
        subprocess.run(args, cwd=cwd, env=environment, check=True)
    run('perl', 'Configure', 'darwin64-x86_64-cc', 'no-shared', 'no-module', 'no-tests',
        '--prefix=/opt/omneum-dependency/openssl', '--openssldir=/etc/ssl',
        cwd=work / 'openssl-3.5.9')
    run('make', '-j2', cwd=work / 'openssl-3.5.9')
    run('make', 'install_sw', 'DESTDIR=' + str(work / 'openssl-staging'),
        cwd=work / 'openssl-3.5.9')
    output.mkdir(parents=True)
    run(sys.executable, '-m', 'pip', 'wheel', '--no-cache-dir', '--no-deps', '--no-build-isolation',
        '--wheel-dir', str(output), str(work / 'cryptography-50.0.2'))
    wheels = list(output.glob('cryptography-50.0.2-*-abi3-macosx_*_x86_64.whl'))
    if len(wheels) != 1:
        raise ValueError('expected one Intel abi3 dependency wheel')
    # Static OpenSSL redistribution carries its upstream license alongside the
    # cryptography licenses. sanitize then regenerates RECORD for these bytes.
    with zipfile.ZipFile(wheels[0], 'a') as archive:
        archive.writestr('cryptography-50.0.2.dist-info/licenses/OpenSSL-LICENSE.txt',
                         (work / 'openssl-3.5.9/LICENSE.txt').read_bytes())
    sanitize(output)
    wheel = wheels[0]
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    (output / 'SHA256SUMS').write_text(f'{digest}  {wheel.name}\n')
    (output / 'BUILD-PROVENANCE.json').write_text(json.dumps({
        'sources': {name: {'url': url, 'sha256': sha} for name, (url, sha) in SOURCES.items()},
        'wheel': wheel.name, 'sha256': digest,
        'rust': subprocess.check_output(['rustc', '--version'], text=True).strip(),
        'python': sys.version, 'static_openssl': '3.5.9',
        'publication': 'unpublished; not resolvable from default PyPI',
    }, indent=2) + '\n')
    print(wheel.name, digest)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build(args.work.resolve(), args.output.resolve())
