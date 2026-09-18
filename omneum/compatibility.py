import json
import re
import subprocess
from pathlib import Path, PurePosixPath


PIN_PATH = Path(__file__).with_name("algorithm_compatibility.json")
PIN_FIELDS = {
    "schema_version",
    "algorithm_id",
    "algorithm_version",
    "specification_repository",
    "git_revision",
    "fixture_revision",
    "manifest_path",
}


def revision(value):
    if (
        not isinstance(value, str)
        or re.fullmatch(r"[0-9a-f]{40}", value) is None
    ):
        raise ValueError("an exact 40-character commit revision is required")
    return value


def relative_path(value):
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("invalid repository path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or str(path) != value:
        raise ValueError("invalid repository path")
    return value


def validate_pin(pin):
    if not isinstance(pin, dict) or set(pin) != PIN_FIELDS:
        raise ValueError("invalid compatibility metadata fields")
    if type(pin["schema_version"]) is not int or pin["schema_version"] != 1:
        raise ValueError("unsupported compatibility schema")
    for field in ("algorithm_id", "algorithm_version"):
        if (
            not isinstance(pin[field], str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", pin[field])
            is None
        ):
            raise ValueError("invalid algorithm identity/version")
    if (
        not isinstance(pin["specification_repository"], str)
        or not pin["specification_repository"].startswith("https://")
    ):
        raise ValueError("specification repository must use HTTPS")
    revision(pin["git_revision"])
    relative_path(pin["manifest_path"])
    if type(pin["fixture_revision"]) is not int or pin["fixture_revision"] < 1:
        raise ValueError("invalid fixture revision")
    return dict(pin)


def load_pin(path=PIN_PATH):
    return validate_pin(json.loads(Path(path).read_text()))


def git(checkout, *arguments):
    result = subprocess.run(
        ["git", "-C", str(checkout), *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        raise ValueError("specification Git object is unavailable")
    return result.stdout


def read_blob(checkout, commit, path):
    revision(commit)
    relative_path(path)
    if git(checkout, "cat-file", "-t", commit).strip() != b"commit":
        raise ValueError("revision must identify a commit")
    entry = git(checkout, "ls-tree", commit, "--", path)
    if not entry.startswith((b"100644 blob ", b"100755 blob ")):
        raise ValueError("specification path must be a regular committed file")
    return git(checkout, "cat-file", "blob", commit + ":" + path)


def load_contract(checkout, pin=None):
    pin = validate_pin(pin if pin is not None else load_pin())
    manifest = json.loads(
        read_blob(checkout, pin["git_revision"], pin["manifest_path"])
    )
    for field in ("algorithm_version", "fixture_revision"):
        if (
            manifest.get(field) != pin[field]
            or type(manifest.get(field)) is not type(pin[field])
        ):
            raise ValueError("pin and manifest disagree")
    if (
        "algorithm_id" in manifest
        and manifest["algorithm_id"] != pin["algorithm_id"]
    ):
        raise ValueError("algorithm identity mismatch")
    for group in ("specification", "reference", "fixtures"):
        paths = manifest.get(group)
        if (
            not isinstance(paths, list)
            or not paths
            or len(set(paths)) != len(paths)
        ):
            raise ValueError("manifest must list unique contract files")
        for path in paths:
            read_blob(checkout, pin["git_revision"], path)
    fixtures = []
    for path in manifest["fixtures"]:
        fixture = json.loads(read_blob(checkout, pin["git_revision"], path))
        if any(
            fixture.get(field) != pin[field]
            or type(fixture.get(field)) is not type(pin[field])
            for field in ("algorithm_version", "fixture_revision")
        ):
            raise ValueError("fixture version mismatch")
        fixtures.append(fixture)
    return pin, manifest, fixtures
