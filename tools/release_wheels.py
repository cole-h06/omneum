"""Validate the release wheel matrix and smoke-test an installed wheel (Python 3.11+)."""

import argparse
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


def smoke(wheels, project):
    with project.open("rb") as source:
        version = tomllib.load(source)["project"]["version"]
    paths = sorted(wheels.glob("*.whl"))
    if len(paths) != 1:
        raise ValueError("smoke test requires exactly one built wheel")
    wheel = paths[0].resolve()
    inspect_wheel(wheel, version)
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

        run("-m", "pip", "install", "--disable-pip-version-check", str(wheel))
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
    parser.add_argument("command", choices=("verify", "prepare", "smoke"))
    parser.add_argument("--project", type=Path, default=Path("pyproject.toml"))
    parser.add_argument("--wheels", type=Path, required=True)
    parser.add_argument("--daemon-assets", type=Path, default=Path("release-assets"))
    parser.add_argument("--tag")
    parser.add_argument("--output", type=Path, default=Path("pypi-dist"))
    args = parser.parse_args()
    if args.command in ("verify", "prepare"):
        if not args.tag:
            parser.error(f"{args.command} requires --tag")
        if args.command == "prepare":
            version = prepare(args.wheels, args.daemon_assets, args.project, args.tag, args.output)
        else:
            version = verify(args.wheels, args.daemon_assets, args.project, args.tag)
    else:
        version = smoke(args.wheels, args.project)
    print(f"Wheel {args.command} passed: {version}")


if __name__ == "__main__":
    main()
