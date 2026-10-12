"""Verify every bundled SDK byte and its license inside a wheel or source archive."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile
import zipfile


def verify(path):
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            files = {name: archive.read(name) for name in archive.namelist() if name.startswith("omneum/mcp/")}
    else:
        with tarfile.open(path) as archive:
            files = {member.name.split("/", 1)[1]: archive.extractfile(member).read()
                     for member in archive if member.isfile() and "/omneum/mcp/" in member.name}
    prefix = "omneum/mcp/"
    manifest = json.loads(files[prefix + "UPSTREAM.json"])
    expected = {prefix + name: digest for name, digest in manifest["files"].items()}
    if set(files) != set(expected) | {prefix + "UPSTREAM.json"}:
        raise ValueError("incomplete or unexpected bundled SDK files")
    for name, digest in expected.items():
        if hashlib.sha256(files[name]).hexdigest() != digest:
            raise ValueError("bundled SDK hash mismatch: " + name)
    return manifest["revision"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", type=Path, nargs="+")
    args = parser.parse_args()
    for pattern in args.artifacts:
        paths = [pattern] if pattern.is_file() else sorted(pattern.parent.glob(pattern.name))
        if not paths:
            raise SystemExit("no matching artifacts: " + str(pattern))
        for path in paths:
            print(path.name, verify(path))


if __name__ == "__main__":
    main()
