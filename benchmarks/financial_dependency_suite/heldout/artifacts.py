import json
import os
import tempfile
from pathlib import Path

from .diagnostics import safe_artifact


def checkpoint(path, records):
    """Atomically publish a durable JSONL prefix, never a partial last line."""
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix=".results-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(safe_artifact(record), sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_jsonl(path, records):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("x", encoding="utf-8") as handle:
        for record in records:
            handle.write(
                json.dumps(
                    record,
                    sort_keys=True,
                    default=str,
                )
                + "\n"
            )


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("x", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                data,
                indent=2,
                sort_keys=True,
                default=str,
            )
            + "\n"
        )
