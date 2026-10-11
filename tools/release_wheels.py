"""Validate the release wheel matrix and smoke-test an installed wheel (Python 3.11+)."""

import argparse
import base64
import csv
import hashlib
import io
import configparser
from email.parser import Parser
import itertools
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import venv
import zipfile

import release_daemon


PYTHONS = ("cp311", "cp312", "cp313", "cp314")
# Preserve the existing wheel matrix. Windows is SDK-only: no local daemon bundle.
PLATFORMS = ("linux-x86_64", "macos-aarch64", "macos-x86_64", "windows-x64")
ENTRY_POINTS = {
    "omneum": "omneum.cli:app",
    "omneum-server": "omneum.proxy:main",
    "omneum-contributor": "omneum.contributor:main",
}
RESOURCES = ("algorithm_compatibility.json", "schemas/research-event-v1.schema.json")


def sanitize(wheels, project=None):
    """Replace local Cargo SBOM identifiers before smoke testing and publication.

    Compiler paths must already be remapped by RUSTFLAGS; fail rather than
    rewriting native binaries. Recompute RECORD after changing SBOM bytes.
    """
    readme = None
    if project is not None:
        with project.open('rb') as source:
            readme_name = tomllib.load(source)['project']['readme']
        if not isinstance(readme_name, str):
            raise ValueError('release README must be a file')
        readme = (project.parent / readme_name).read_bytes()
    for path in sorted(wheels.glob("*.whl")):
        with zipfile.ZipFile(path) as archive:
            entries = [(info, archive.read(info.filename)) for info in archive.infolist()]
        normalized = []
        record = None
        for info, data in entries:
            if info.filename.endswith('.dist-info/RECORD'):
                record = info
                continue
            if readme is not None and info.filename.endswith('.dist-info/METADATA'):
                header, separator, _ = data.partition(b'\n\n')
                if not separator:
                    raise ValueError('wheel METADATA has no description boundary')
                data = header + separator + readme
            if '/sboms/' in info.filename and info.filename.endswith('.json'):
                document = json.loads(data)
                def rewrite(value):
                    if isinstance(value, dict):
                        return {key: rewrite(item) for key, item in value.items()}
                    if isinstance(value, list):
                        return [rewrite(item) for item in value]
                    if isinstance(value, str):
                        return re.sub(r'path\+file://[^#]+#([^" ]+)', r'pkg:cargo/\1', value)
                    return value
                data = (json.dumps(rewrite(document), sort_keys=True) + '\n').encode()
            if re.search(rb'(?:/Users/|/home/runner/|[A-Z]:\\Users\\)', data):
                raise ValueError(f'unremapped developer path: {info.filename}')
            normalized.append((info, data))
        if record is None:
            raise ValueError('wheel has no RECORD')
        rows = [[info.filename, 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode(), str(len(data))]
                for info, data in normalized]
        rows.append([record.filename, '', ''])
        output = io.StringIO(newline='')
        csv.writer(output, lineterminator='\n').writerows(rows)
        with tempfile.TemporaryDirectory(dir=path.parent) as directory:
            candidate = Path(directory) / path.name
            with zipfile.ZipFile(candidate, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                for info, data in normalized:
                    archive.writestr(info, data)
                archive.writestr(record, output.getvalue())
            candidate.replace(path)


def platform_for_tag(tag):
    if re.fullmatch(r"manylinux(?:_[0-9]+_[0-9]+|1|2010|2014)_x86_64", tag):
        return "linux-x86_64"
    if re.fullmatch(r"macosx_[0-9]+_[0-9]+_arm64", tag):
        return "macos-aarch64"
    if re.fullmatch(r"macosx_[0-9]+_[0-9]+_x86_64", tag):
        return "macos-x86_64"
    if tag == "win_amd64":
        return "windows-x64"
    raise ValueError(f"unsupported wheel platform tag: {tag}")


def inspect_wheel(path, version):
    if path.is_symlink() or not path.is_file() or path.suffix != ".whl":
        raise ValueError(f"invalid wheel: {path}")
    parts = path.stem.split("-")
    if len(parts) != 5:
        raise ValueError(f"unexpected wheel filename: {path.name}")
    name, wheel_version, python, abi, platforms = parts
    if name != "omneum" or wheel_version != version:
        raise ValueError(f"wheel name/version must be omneum {version}: {path.name}")
    if python not in PYTHONS or abi != python:
        raise ValueError(f"unsupported Python/ABI: {path.name}")
    targets = {platform_for_tag(tag) for tag in platforms.split(".")}
    if len(targets) != 1:
        raise ValueError(f"mixed wheel platforms: {path.name}")
    info = f"omneum-{version}.dist-info"
    with zipfile.ZipFile(path) as wheel:
        names = wheel.namelist()
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate wheel members: {path.name}")
        metadata = Parser().parsestr(wheel.read(f"{info}/METADATA").decode())
        if metadata.get_all("Name") != ["omneum"] or metadata.get_all("Version") != [version]:
            raise ValueError(f"wheel metadata name/version mismatch: {path.name}")
        tags = Parser().parsestr(wheel.read(f"{info}/WHEEL").decode()).get_all("Tag", [])
        if set(tags) != {f"{python}-{abi}-{tag}" for tag in platforms.split(".")}:
            raise ValueError(f"wheel metadata tags mismatch: {path.name}")
        entries = configparser.ConfigParser()
        entries.read_string(wheel.read(f"{info}/entry_points.txt").decode())
        if dict(entries["console_scripts"]) != ENTRY_POINTS:
            raise ValueError(f"wheel console entry points mismatch: {path.name}")
        for resource in RESOURCES:
            if not wheel.read(f"omneum/{resource}"):
                raise ValueError(f"empty packaged resource: {resource}")
    return python, targets.pop()


def verify(wheels, daemon_assets, project, tag):
    version = release_daemon.version_for_tag(project, tag)
    expected = set(itertools.product(PYTHONS, PLATFORMS))
    found = set()
    for path in sorted(wheels.rglob("*.whl")):
        target = inspect_wheel(path, version)
        if target in found:
            raise ValueError(f"duplicate wheel target: {target}")
        found.add(target)
    if found != expected:
        raise ValueError(f"missing wheel targets: {sorted(expected - found)}")
    # Includes exact asset names, all three checksums, archive layout, and Linux runtime version.
    release_daemon.verify(daemon_assets, version)
    return version


def prepare(wheels, daemon_assets, project, tag, destination):
    """Stage only the verified matrix for PyPI, preserving the tested wheel bytes."""
    if destination.exists() or destination.is_symlink():
        raise ValueError("wheel release destination must not already exist")
    version = verify(wheels, daemon_assets, project, tag)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".wheel-release-", dir=destination.parent) as temporary:
        output = Path(temporary) / "wheels"
        output.mkdir()
        for path in sorted(wheels.rglob("*.whl")):
            shutil.copyfile(path, output / path.name)
        verify(output, daemon_assets, project, tag)
        output.rename(destination)
    return version


def verify_intel_dependency(path):
    """Verify the explicitly supplied diagnostic wheel; default PyPI is unchanged."""
    if path.name != 'cryptography-50.0.2-cp311-abi3-macosx_10_13_x86_64.whl' or path.is_symlink():
        raise ValueError('unexpected Intel dependency wheel')
    manifest = path.parent / 'SHA256SUMS'
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if manifest.is_symlink() or manifest.read_bytes() != f'{digest}  {path.name}\n'.encode():
        raise ValueError('Intel dependency checksum mismatch')
    with zipfile.ZipFile(path) as archive:
        metadata = Parser().parsestr(archive.read('cryptography-50.0.2.dist-info/METADATA').decode())
        if metadata.get_all('Name') != ['cryptography'] or metadata.get_all('Version') != ['50.0.2']:
            raise ValueError('Intel dependency metadata mismatch')
    return path.resolve()


def smoke(wheels, project, dependency_wheel=None):
    with project.open("rb") as source:
        version = tomllib.load(source)["project"]["version"]
    paths = sorted(wheels.glob("*.whl"))
    if len(paths) != 1:
        raise ValueError("smoke test requires exactly one built wheel")
    wheel = paths[0].resolve()
    inspect_wheel(wheel, version)
    dependency = [str(verify_intel_dependency(dependency_wheel))] if dependency_wheel else []
    # Neither the checkout nor the development environment supplies installed imports.
    env = {key: value for key, value in os.environ.items()
           if key not in {"PYTHONPATH", "PYTHONHOME"}}
    with tempfile.TemporaryDirectory(prefix="omneum-wheel-") as temporary:
        root = Path(temporary)
        environment = root / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        scripts = environment / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")

        def run(*args):
            subprocess.run([str(python), "-I", *args], cwd=root, env=env, check=True)

        run("-m", "pip", "install", "--only-binary=:all:", "--disable-pip-version-check", str(wheel), *dependency)
        run("-m", "pip", "check")
        run("-c", """
import importlib.metadata as metadata
import importlib.resources as resources
import json
from pathlib import Path
import sys
import omneum, omneum.server, omneum.installation, omneum.proxy, omneum.contributor, omneum_oprf
assert metadata.version('omneum') == sys.argv[1]
for module in (omneum, omneum.server, omneum.installation, omneum.proxy, omneum.contributor, omneum_oprf):
    assert Path(module.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()), module.__file__
for name in ('algorithm_compatibility.json', 'schemas/research-event-v1.schema.json'):
    json.loads(resources.files('omneum').joinpath(name).read_text())
entries = {entry.name: entry for entry in metadata.distribution('omneum').entry_points
           if entry.group == 'console_scripts'}
assert {name: entry.value for name, entry in entries.items()} == json.loads(sys.argv[2])
assert all(callable(entry.load()) for entry in entries.values())
""", version, json.dumps(ENTRY_POINTS))
        cli = scripts / ("omneum.exe" if os.name == "nt" else "omneum")
        subprocess.run([str(cli), "install", "--help"], cwd=root, env=env, check=True)
    return version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("verify", "prepare", "smoke", "sanitize"))
    parser.add_argument("--project", type=Path, default=Path("pyproject.toml"))
    parser.add_argument("--wheels", type=Path, required=True)
    parser.add_argument("--dependency-wheel", type=Path,
                        help="explicit verified Intel wheel for unpublished diagnostics only")
    parser.add_argument("--daemon-assets", type=Path, default=Path("release-assets"))
    parser.add_argument("--tag")
    parser.add_argument("--output", type=Path, default=Path("pypi-dist"))
    args = parser.parse_args()
    if args.command == "sanitize":
        sanitize(args.wheels, args.project)
        print("Wheel paths normalized")
        return
    if args.command in ("verify", "prepare"):
        if not args.tag:
            parser.error(f"{args.command} requires --tag")
        if args.command == "prepare":
            version = prepare(args.wheels, args.daemon_assets, args.project, args.tag, args.output)
        else:
            version = verify(args.wheels, args.daemon_assets, args.project, args.tag)
    else:
        version = smoke(args.wheels, args.project, args.dependency_wheel)
    print(f"Wheel {args.command} passed: {version}")


if __name__ == "__main__":
    main()
