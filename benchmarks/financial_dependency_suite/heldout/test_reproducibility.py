import pytest

from benchmarks.financial_dependency_suite.reproducibility import (
    write_manifest,
)


def test_manifest_is_immutable(tmp_path):
    path = tmp_path / "manifest.json"
    data = {
        "benchmark": "heldout",
        "track": "application",
    }

    write_manifest(path, data)

    with pytest.raises(FileExistsError):
        write_manifest(path, data)
