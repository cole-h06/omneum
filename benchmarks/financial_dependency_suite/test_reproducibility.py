from benchmarks.financial_dependency_suite.reproducibility import (
    manifest,
    sha256_file,
    write_manifest,
)


def test_manifest(tmp_path):
    source = tmp_path / "input.txt"
    source.write_text("omneum", encoding="utf-8")

    data = manifest(
        benchmark="source_dependence",
        track="structural",
        trials=10,
        context_budget=6,
        models={"omneum": "dependency-estimator-v4"},
        inputs=[source],
        identifier="test-run",
    )

    assert data["run_id"] == "test-run"
    assert data["benchmark"] == "source_dependence"
    assert data["track"] == "structural"
    assert data["trials"] == 10
    assert data["context_budget"] == 6
    assert data["estimator"]["upstream_weight"] == 25.0
    assert data["estimator"]["retrieval_weight"] == 0.0
    assert data["inputs"][str(source)] == sha256_file(source)
    assert "commit" in data["git"]
    assert "dirty" in data["git"]
    assert "anthropic" in data["packages"]

    output = tmp_path / "manifest.json"
    write_manifest(output, data)

    assert output.exists()
    assert '"run_id": "test-run"' in output.read_text()
