"""Prepare/verify release assets from CI's staged daemons (Python 3.11+)."""

import argparse
import gzip
import hashlib
from pathlib import Path
import re
import tarfile
import tempfile
import tomllib
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "omneum"))
from runtime_bundle import unpack


PLATFORMS = ("linux-x86_64", "macos-aarch64", "macos-x86_64")
MANIFEST = "SHA256SUMS"


def layout(platform):
    if platform not in PLATFORMS:
        raise ValueError(f"unsupported platform: {platform}")
    if platform.startswith("linux-"):
        return {
            "LICENSE": 0o644,
            "NATIVE-LICENSES.txt": 0o644,
            "omneumd": 0o755,
            "omneum-server": 0o755,
            "install-server.sh": 0o755,
            "install_server.py": 0o644,
            "install-linux.py": 0o644,
            "runtime_bundle.py": 0o644,
            "runtime.tar.gz": 0o644,
            "systemd/omneum-server.socket": 0o644,
            "systemd/omneum-server@.service": 0o644,
            "sysusers.d/omneum-server.conf": 0o644,
            "install.sh": 0o755,
            "install-foreground.sh": 0o755,
            "systemd": 0o755,
            "systemd/omneumd.service": 0o644,
            "sysusers.d": 0o755,
            "sysusers.d/omneum.conf": 0o644,
        }
    return {
        "LICENSE": 0o644,
        "NATIVE-LICENSES.txt": 0o644,
        "omneumd": 0o755,
        "install-macos.sh": 0o755,
        "launchd": 0o755,
        "launchd/ai.omneum.omneumd.plist": 0o644,
    }


def version_for_tag(project, tag):
    with project.open("rb") as source:
        version = tomllib.load(source)["project"]["version"]
    # A path/URL-safe spelling, without normalizing away exact tag differences.
    if not isinstance(version, str) or not re.fullmatch(r"[0-9][A-Za-z0-9.!+_-]*", version):
        raise ValueError("project.version is not safe for release asset names")
    if tag != f"v{version}":
        raise ValueError(f"release tag must be exactly v{version}; got {tag!r}")
    cargo = project.with_name('Cargo.toml')
    if cargo.exists():
        with cargo.open('rb') as source:
            if tomllib.load(source)['package']['version'] != version:
                raise ValueError('Rust package version must match Python release version')
    return version


def archive_name(version, platform):
    return f"omneum-daemon-{version}-{platform}.tar.gz"


def checksum_manifest(directory, version):
    lines = []
    for platform in PLATFORMS:
        name = archive_name(version, platform)
        path = directory / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"missing or invalid archive: {name}")
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        lines.append(f"{digest}  {name}\n")
    return "".join(lines)


def verify(directory, version):
    expected = {archive_name(version, p) for p in PLATFORMS} | {MANIFEST}
    if directory.is_symlink() or {p.name for p in directory.iterdir()} != expected:
        raise ValueError("release asset set is incomplete or contains unexpected assets")
    manifest = directory / MANIFEST
    if manifest.is_symlink() or not manifest.is_file():
        raise ValueError("missing or invalid checksum manifest")
    if manifest.read_bytes() != checksum_manifest(directory, version).encode("ascii"):
        raise ValueError("checksum manifest does not match release archives")
    for platform in PLATFORMS:
        expected_layout = layout(platform)
        with tarfile.open(directory / archive_name(version, platform), "r:gz") as archive:
            members = archive.getmembers()
            if [m.name for m in members] != sorted(expected_layout):
                raise ValueError(f"invalid archive layout: {platform}")
            root = Path(__file__).resolve().parents[1]
            for name, source in [('LICENSE', root / 'LICENSE'),
                                 ('NATIVE-LICENSES.txt', root / 'omneum/NATIVE-LICENSES.txt')]:
                if archive.extractfile(name).read() != source.read_bytes():
                    raise ValueError('release license bytes differ from verified source: ' + name)
            daemon_member = archive.getmember("omneumd")
            if not daemon_member.isfile() or not 0 < daemon_member.size <= 128 * 1024 * 1024:
                raise ValueError("invalid daemon archive member")
            binary = archive.extractfile(daemon_member).read()
            if b"protected-voprf-v1" not in binary or b"fixture-voprf-v1" in binary:
                raise ValueError("release daemon is not a protected evaluator build")
            if platform == "linux-x86_64":
                with archive.extractfile("runtime.tar.gz") as runtime:
                    unpack(runtime, version=version)
            for member in members:
                is_directory = member.name in {"systemd", "sysusers.d", "launchd"}
                valid_type = member.isdir() if is_directory else member.isfile() and member.size > 0
                if not valid_type:
                    raise ValueError(f"invalid archive member: {member.name}")
                if (member.mode != expected_layout[member.name] or member.uid != 0
                        or member.gid != 0 or member.mtime != 0 or member.uname or member.gname):
                    raise ValueError(f"invalid archive metadata: {member.name}")


def prepare(staging, destination, version):
    # Publish the directory only once all archives and their manifest verify.
    if destination.exists() or destination.is_symlink():
        raise ValueError("release destination must not already exist")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".daemon-release-", dir=destination.parent) as temporary:
        output = Path(temporary) / "assets"
        output.mkdir()
        for platform in PLATFORMS:
            source = staging / f"daemon-{platform}"
            expected = layout(platform)
            if source.is_symlink() or not source.is_dir():
                raise ValueError(f"missing platform artifact: {platform}")
            if {p.relative_to(source).as_posix() for p in source.rglob("*")} != set(expected):
                raise ValueError(f"incomplete or unexpected staged contents: {platform}")
            with (output / archive_name(version, platform)).open("wb") as raw:
                with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=9) as compressed:
                    with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as archive:
                        for name, mode in sorted(expected.items()):
                            path = source / name
                            if path.is_symlink() or not (path.is_dir() or path.is_file()):
                                raise ValueError(f"invalid staged member: {path}")
                            member = tarfile.TarInfo(name)
                            member.mode = mode
                            if path.is_dir():
                                member.type = tarfile.DIRTYPE
                                archive.addfile(member)
                            else:
                                member.size = path.stat().st_size
                                with path.open("rb") as contents:
                                    archive.addfile(member, contents)
        (output / MANIFEST).write_text(checksum_manifest(output, version), encoding="ascii")
        verify(output, version)
        output.rename(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "prepare", "verify"))
    parser.add_argument("--project", type=Path, default=Path("pyproject.toml"))
    parser.add_argument("--tag", required=True)
    parser.add_argument("--staging", type=Path, default=Path("daemon-artifacts"))
    parser.add_argument("--output", type=Path, default=Path("release-assets"))
    args = parser.parse_args()
    version = version_for_tag(args.project, args.tag)
    if args.command == "prepare":
        prepare(args.staging, args.output, version)
    elif args.command == "verify":
        verify(args.output, version)
    print(version)


if __name__ == "__main__":
    main()
