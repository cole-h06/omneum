"""Resolve recorded artifact names and verify explicit public representations."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CURRENT = "benchmarks/context_evaluation/"
HISTORICAL = "benchmarks/financial_dependency_suite/"


def publication_contract(root=ROOT):
    return json.loads((Path(root) / CURRENT / "publication_manifest_v1.json").read_text())


def _benchmark_path(recorded):
    text = Path(recorded).as_posix()
    for prefix in (HISTORICAL, CURRENT):
        marker = "/" + prefix
        if text.startswith(prefix) or marker in text:
            suffix = text[len(prefix):] if text.startswith(prefix) else text.split(marker, 1)[1]
            if ".." in Path(suffix).parts:
                raise ValueError("Artifact path escapes benchmark directory")
            return prefix + suffix
    return None


def resolve_artifact(recorded, *, root=ROOT, expected_sha256=None):
    """Resolve retained artifacts; a requested digest must match actual bytes."""
    root = Path(root)
    name = _benchmark_path(recorded)
    if name is None:
        path = Path(recorded)
        return path if path.is_absolute() else root / path
    manifest = publication_contract(root)
    canonical = name.replace(HISTORICAL, CURRENT, 1)
    current = root / canonical
    representation = manifest["representations"].get(canonical)
    snapshot = manifest["historical_sources"].get(canonical)
    saved = root / snapshot["path"] if snapshot else current
    candidates = (saved, current) if name.startswith(HISTORICAL) else (current, saved)
    if expected_sha256 is not None:
        for path in candidates:
            if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == expected_sha256:
                return path
        raise ValueError(f"Preserved artifact digest mismatch: {recorded}")
    if representation:
        return root / representation["path"]
    return candidates[0]


def verify_recorded_artifact(recorded, digest, *, root=ROOT):
    """Verify original bytes or a declared projection; never equate their hashes."""
    name = _benchmark_path(recorded)
    canonical = name.replace(HISTORICAL, CURRENT, 1) if name else None
    representation = publication_contract(root)["representations"].get(canonical)
    if representation:
        if digest != representation["original_sha256"]:
            raise ValueError(f"Original evidence digest mismatch: {recorded}")
        path = Path(root) / representation["path"]
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
        path = ROOT / name.replace(HISTORICAL, CURRENT, 1) if name else Path(recorded)
        if path.resolve() == current:
            matches.add(digest)
    if len(matches) > 1:
        raise ValueError("Conflicting recorded input digests")
    return next(iter(matches), None)
