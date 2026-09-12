import json
from pathlib import Path


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
