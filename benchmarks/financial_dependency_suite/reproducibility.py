from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from .config import estimator_config


PACKAGES = (
    "anthropic",
    "openai",
    "google-genai",
    "cohere",
    "sentence-transformers",
    "numpy",
)


def run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _git(*args: str) -> str | None:
    try:
        return subprocess.check_output(
            ["git", *args],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def git_state() -> dict[str, Any]:
    commit = _git("rev-parse", "HEAD")
    status = _git("status", "--porcelain")
    return {
        "commit": commit,
        "dirty": bool(status) if status is not None else None,
    }


def package_versions() -> dict[str, str | None]:
    result = {}
    for package in PACKAGES:
        try:
            result[package] = version(package)
        except PackageNotFoundError:
            result[package] = None
    return result


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest(
    *,
    benchmark: str,
    track: str,
    trials: int,
    context_budget: int | None = None,
    models: dict[str, str] | None = None,
    inputs: list[str | Path] | None = None,
    identifier: str | None = None,
) -> dict[str, Any]:
    identifier = identifier or run_id()

    input_hashes = {}
    for path in inputs or []:
        path = Path(path)
        input_hashes[str(path)] = sha256_file(path)

    return {
        "run_id": identifier,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "benchmark": benchmark,
        "track": track,
        "trials": trials,
        "context_budget": context_budget,
        "git": git_state(),
        "python": {
            "version": sys.version,
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
        },
        "packages": package_versions(),
        "models": models or {},
        "estimator": asdict(estimator_config()),
        "inputs": input_hashes,
    }


def write_manifest(path: str | Path, data: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
