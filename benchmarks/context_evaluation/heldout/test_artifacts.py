import json

import pytest

from benchmarks.context_evaluation.heldout.artifacts import (
    write_json,
    write_jsonl,
)


def test_jsonl_is_immutable(tmp_path):
    path = tmp_path / "results.jsonl"
    records = [
        {"case_id": "a", "score": 1},
        {"case_id": "b", "score": 0},
    ]

    write_jsonl(path, records)

    lines = path.read_text().splitlines()

    assert [json.loads(line) for line in lines] == records

    with pytest.raises(FileExistsError):
        write_jsonl(path, records)


def test_json_is_immutable(tmp_path):
    path = tmp_path / "summary.json"
    data = {"accuracy": 0.75}

    write_json(path, data)

    assert json.loads(path.read_text()) == data

    with pytest.raises(FileExistsError):
        write_json(path, data)
