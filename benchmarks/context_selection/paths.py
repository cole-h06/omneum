"""Resolve recorded artifact names and verify explicit public representations."""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CURRENT = "benchmarks/context_selection/"
RECORDED = "benchmarks/context_evaluation/"
HISTORICAL = "benchmarks/financial_dependency_suite/"


def publication_contract(root=ROOT):
    return json.loads((Path(root) / CURRENT / "publication_manifest_v1.json").read_text())


def _benchmark_path(recorded):
    text = Path(recorded).as_posix()
    for prefix in (HISTORICAL, RECORDED, CURRENT):
        marker = "/" + prefix
        if text.startswith(prefix) or marker in text:
            suffix = text[len(prefix):] if text.startswith(prefix) else text.split(marker, 1)[1]
            if ".." in Path(suffix).parts:
                raise ValueError("Artifact path escapes benchmark directory")
            if prefix == CURRENT:
                if suffix.startswith("synthetic/"):
                    suffix = "heldout/" + suffix[len("synthetic/"):]
                prefix = RECORDED
            return prefix + suffix
    return None


def _relocated_path(recorded):
    """Map frozen filesystem identities without rewriting provenance metadata."""
    name = _benchmark_path(recorded)
    if name is None:
        return Path(recorded)
    suffix = name.split("/", 2)[2]
    if suffix.startswith("heldout/"):
        suffix = "synthetic/" + suffix[len("heldout/"):]
    return Path(CURRENT) / suffix


def resolve_artifact(recorded, *, root=ROOT, expected_sha256=None):
    """Resolve retained artifacts; a requested digest must match actual bytes."""
    root = Path(root)
    if expected_sha256 is not None and (type(expected_sha256) is not str or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None):
        raise ValueError("expected_sha256 must be a lowercase SHA-256 digest")
    name = _benchmark_path(recorded)
    if name is None:
        path = Path(recorded)
        path = path if path.is_absolute() else root / path
        if expected_sha256 is None:
            return path
        archives = [root / CURRENT / 'synthetic/contracts' / directory / (expected_sha256 + '.txt')
                    for directory in ('publication-v1', 'execution-v1')]
        for candidate in (path, *archives):
            if candidate.is_file() and hashlib.sha256(candidate.read_bytes()).hexdigest() == expected_sha256:
                return candidate
        raise ValueError(f"Preserved artifact digest mismatch: {recorded}")
    manifest = publication_contract(root)
    canonical = name.replace(HISTORICAL, RECORDED, 1)
    current = root / _relocated_path(canonical)
    representation = manifest["representations"].get(canonical)
    snapshot = manifest["historical_sources"].get(canonical)
    saved = root / _relocated_path(snapshot["path"]) if snapshot else current
    candidates = (saved, current) if name.startswith(HISTORICAL) else (current, saved)
    if expected_sha256 is not None:
        archive = root / CURRENT / "synthetic/contracts/publication-v1" / (expected_sha256 + ".txt")
        execution_archive = root / CURRENT / 'synthetic/contracts/execution-v1' / (expected_sha256 + '.txt')
        for path in (*candidates, archive, execution_archive):
            if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == expected_sha256:
                return path
        raise ValueError(f"Preserved artifact digest mismatch: {recorded}")
    if representation:
        return root / _relocated_path(representation["path"])
    if not candidates[0].is_file() and canonical in manifest['artifacts']:
        digest = manifest['artifacts'][canonical]
        archive = root / CURRENT / 'synthetic/contracts/publication-v1' / (digest + '.txt')
        if archive.exists():
            return resolve_artifact(recorded, root=root, expected_sha256=digest)
    return candidates[0]


def verify_recorded_artifact(recorded, digest, *, root=ROOT):
    """Verify original bytes or a declared projection; never equate their hashes."""
    name = _benchmark_path(recorded)
    canonical = name.replace(HISTORICAL, RECORDED, 1) if name else None
    representation = publication_contract(root)["representations"].get(canonical)
    if representation:
        if digest != representation["original_sha256"]:
            raise ValueError(f"Original evidence digest mismatch: {recorded}")
        path = Path(root) / _relocated_path(representation["path"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != representation["sha256"]:
            raise ValueError(f"Public representation digest mismatch: {recorded}")
        metadata = json.loads(path.read_text())["public_representation"]
        if metadata["version"] != 1 or metadata["original_sha256"] != digest:
            raise ValueError(f"Public representation provenance mismatch: {recorded}")
        return path
    return resolve_artifact(recorded, root=root, expected_sha256=digest)


def public_manifest(directory):
    return Path(directory) / "manifest.public-v1.json"


def input_digest(inputs, current):
    """Match relocated fixtures by their full logical identity, never basename."""
    current = Path(current).resolve()
    matches = set()
    for recorded, digest in inputs.items():
        name = _benchmark_path(recorded)
        path = ROOT / _relocated_path(name) if name else Path(recorded)
        if path.resolve() == current:
            matches.add(digest)
    if len(matches) > 1:
        raise ValueError("Conflicting recorded input digests")
    return next(iter(matches), None)
