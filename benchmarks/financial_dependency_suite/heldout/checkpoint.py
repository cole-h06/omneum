"""Locked, validated continuation of committed trial records."""

import fcntl
import hashlib
import json
from pathlib import Path

from .artifacts import checkpoint


def implementation_hash():
    root = Path(__file__).resolve().parents[3]
    paths = []
    for directory, pattern in (("benchmarks/financial_dependency_suite", "*.py"),
                               ("omneum", "*.py"), ("src", "*.rs")):
        paths.extend(p for p in (root / directory).rglob(pattern)
                     if not p.name.startswith("test_"))
    paths.extend(root / name for name in ("Cargo.lock", "uv.lock", "pyproject.toml"))
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def record_key(record):
    return record["case_id"], record["method"], record["trial"]


class TrialCheckpoint:
    def __init__(self, directory, contract, schedule, *, resume=False):
        self.directory = Path(directory)
        self.contract = contract
        self.schedule = schedule
        self.resume = resume
        self.records = []
        self.lock = None

    def __enter__(self):
        if not self.resume:
            self.directory.mkdir(parents=True, exist_ok=False)
        elif not self.directory.is_dir():
            raise ValueError("resume directory does not exist")
        self.lock = (self.directory / ".run.lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if self.resume:
                saved = json.loads((self.directory / "manifest.json").read_text())
                if saved.get("checkpoint_contract") != self.contract:
                    raise ValueError("resume contract mismatch; refusing to mix runs")
                path = self.directory / "results.jsonl"
                self.records = [json.loads(line) for line in path.read_text().splitlines()]
                keys = [record_key(record) for record in self.records]
                if keys != self.schedule[:len(keys)]:
                    raise ValueError("resume records are not a valid schedule prefix")
                if any(record.get("answer_score") not in {
                    "correct", "incorrect", "unscored", "selection_failure", "generation_failure",
                } for record in self.records):
                    raise ValueError("resume record has invalid answer_score")
            else:
                checkpoint(self.directory / "results.jsonl", [])
            return self
        except BaseException:
            self.lock.close()
            raise

    def commit(self, record):
        if record_key(record) != self.schedule[len(self.records)]:
            raise ValueError("trial completed out of schedule order")
        updated = [*self.records, record]
        checkpoint(self.directory / "results.jsonl", updated)
        self.records = updated

    def __exit__(self, *args):
        self.lock.close()
