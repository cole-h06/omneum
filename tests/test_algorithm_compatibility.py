import copy
import os
from pathlib import Path

import pytest

from omneum import compatibility, conformance


CHECKOUT = Path(
    os.environ.get(
        "ALGORITHM_SPEC_CHECKOUT",
        str(Path(__file__).resolve().parents[2] / "braid"),
    )
)


def test_pinned_conformance():
    result = conformance.check(CHECKOUT)
    assert result["passed"] is True
    assert result["cases"] == {
        "propagation": 8,
        "fusion": 8,
        "clusters": 3,
        "records": 18,
    }
    assert (
        result["compatibility"]["git_revision"]
        == "2405ec3375f8daf8fe25e5dff1a58c120d3e75ca"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("git_revision", "main"),
        ("git_revision", "92e9812"),
        ("git_revision", "0" * 40),
        ("algorithm_version", "not-the-version"),
        ("fixture_revision", 2),
        ("fixture_revision", True),
        ("schema_version", 2),
        ("manifest_path", "../secret"),
        ("manifest_path", "/secret"),
        ("algorithm_id", ""),
    ],
)
def test_invalid_pin_fails_closed(field, value):
    pin = compatibility.load_pin()
    pin[field] = value
    with pytest.raises(ValueError):
        conformance.check(CHECKOUT, pin)


def test_extra_pin_field_rejected():
    pin = compatibility.load_pin()
    pin["arbitrary"] = "value"
    with pytest.raises(ValueError):
        compatibility.validate_pin(pin)


def test_fixture_mismatch(monkeypatch):
    original = compatibility.read_blob

    def changed(checkout, revision, path):
        data = original(checkout, revision, path)
        if path.endswith("braid_sync_v1.json"):
            return data.replace(
                b'"fixture_revision": 1', b'"fixture_revision": 2'
            )
        return data

    monkeypatch.setattr(compatibility, "read_blob", changed)
    with pytest.raises(ValueError, match="fixture version"):
        conformance.check(CHECKOUT)


def test_dirty_checkout_files_not_read(monkeypatch):
    def forbidden(*arguments, **keywords):
        raise AssertionError("working-tree content must not be read")

    pin = compatibility.load_pin()
    monkeypatch.setattr(Path, "read_text", forbidden)
    assert conformance.check(CHECKOUT, pin)["passed"]


@pytest.mark.parametrize(
    "change", ["missing_group", "new_group", "bad_expectation", "empty_group"]
)
def test_fixture_coverage_and_outputs_are_enforced(monkeypatch, change):
    pin, manifest, fixtures = compatibility.load_contract(CHECKOUT)
    fixtures = copy.deepcopy(fixtures)
    first = next(fixture for fixture in fixtures if "propagation" in fixture)
    if change == "missing_group":
        del first["propagation"]
    elif change == "new_group":
        first["unknown"] = []
    elif change == "empty_group":
        first["propagation"] = []
    else:
        first["propagation"][0]["expected"]["iterations"] = 999
    monkeypatch.setattr(
        conformance, "load_contract", lambda *args: (pin, manifest, fixtures)
    )
    with pytest.raises((AssertionError, ValueError)):
        conformance.check(CHECKOUT)


def test_candidate_failure_does_not_write_pin(monkeypatch):
    before = compatibility.PIN_PATH.read_bytes()
    monkeypatch.setattr(conformance.inference, "CONVERGENCE_TOLERANCE", 0.1)
    with pytest.raises(AssertionError):
        conformance.check(CHECKOUT)
    assert compatibility.PIN_PATH.read_bytes() == before
