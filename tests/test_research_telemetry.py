import asyncio
import json
import os
import subprocess
import warnings
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from omneum.client import _map_assertion_evaluation
from omneum.dependency import (
    DependencyEstimatorConfig,
    SIGNALS,
    estimate_dependencies,
)
from omneum.engine_graph import AssertionTriple, SourcePair, build_graph
from omneum.inference import infer, InferenceError
from omneum.information import Source, Claim, Observation
from omneum.research_telemetry import (
    EvaluationContext,
    ImplementationProvenance,
    JsonlResearchRecorder,
    ResearchEvent,
    build_event,
    checkout_provenance,
    record_evaluation,
    summarize,
)


def estimator():
    return DependencyEstimatorConfig(
        **{name + "_weight": 1.0 for name in SIGNALS},
        temporal_window_seconds=7200.0,
    )


def context():
    return EvaluationContext(
        run_id=uuid4(), implementation=ImplementationProvenance()
    )


def evaluation():
    graph = build_graph([AssertionTriple("source", "attribute", "claim")], [])
    return _map_assertion_evaluation(
        infer(graph),
        {
            "source": Source(
                "web_publisher", "private-customer.example", "secret-owner"
            )
        },
        {
            "claim": Claim(
                "service",
                "private-entity",
                "private-attribute",
                "PRIVATE DOCUMENT API_KEY=secret",
            )
        },
        (),
        None,
    )


def event():
    return build_event(
        context=context(),
        estimator=estimator(),
        latency_ms=1.0,
        evaluation=evaluation(),
    )


def test_event_excludes_private_fields():
    encoded = event().model_dump_json()
    for secret in (
        "private-customer",
        "secret-owner",
        "private-entity",
        "private-attribute",
        "PRIVATE DOCUMENT",
        "API_KEY",
    ):
        assert secret not in encoded


def test_event_algorithm_revision():
    assert (
        event().algorithm.revision
        == "92e981234070da566e9186015ace4a41cbebc644"
    )


def test_single_source_aggregates():
    value = event()
    assert value.graph.sources == 1
    assert value.graph.claims == 1
    assert value.graph.attributes == 1
    assert value.graph.edges == 1
    assert value.graph.pairs == 0
    assert value.dependency.mean is None


def test_default_implementation_revision():
    assert event().context.implementation.revision is None


def test_event_round_trip():
    value = event()
    encoded = value.model_dump_json()
    assert ResearchEvent.model_validate_json(encoded) == value


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda value: value.update(prompt="SECRET"), id="extra-event-field"
        ),
        pytest.param(
            lambda value: value["context"].update(raw_data="SECRET"),
            id="extra-context-field",
        ),
        pytest.param(
            lambda value: value["estimator"].update(api_key="SECRET"),
            id="extra-estimator-field",
        ),
        pytest.param(
            lambda value: value.update(schema_version=2), id="schema-version"
        ),
        pytest.param(
            lambda value: value.update(latency_ms=float("nan")),
            id="nonfinite-latency",
        ),
        pytest.param(
            lambda value: value.update(event_id="customer-name"),
            id="invalid-event-id",
        ),
        pytest.param(
            lambda value: value["algorithm"].update(revision="main"),
            id="invalid-revision",
        ),
        pytest.param(
            lambda value: value.update(timestamp="2026-01-01T00:00:00"),
            id="naive-timestamp",
        ),
        pytest.param(
            lambda value: value["graph"].update(pairs=3),
            id="pair-count-mismatch",
        ),
    ],
)
def test_schema_rejects_extra_or_invalid_data(mutate):
    value = json.loads(event().model_dump_json())
    mutate(value)
    with pytest.raises(ValidationError):
        ResearchEvent.model_validate_json(json.dumps(value))


def test_json_schema_matches_checked_in_schema():
    schema_path = (
        Path(__file__).resolve().parents[1]
        / "omneum/schemas/research-event-v1.schema.json"
    )
    expected = json.loads(schema_path.read_text())
    assert expected == ResearchEvent.model_json_schema()


def test_durable_append(tmp_path):
    path = tmp_path / "private" / "events.jsonl"
    recorder = JsonlResearchRecorder(path)
    recorder.record(event())
    recorder.record(event())
    lines = path.read_text().splitlines()
    assert len(lines) == 2
    for line in lines:
        ResearchEvent.model_validate_json(line)
    if os.name == "posix":
        assert path.stat().st_mode & 0o077 == 0


@pytest.mark.skipif(os.name != "posix", reason="POSIX file permissions")
def test_refuse_public_file(tmp_path):
    target = tmp_path / "public.jsonl"
    target.write_text("")
    target.chmod(0o644)
    with pytest.raises(ValueError):
        JsonlResearchRecorder(target).record(event())
    assert target.read_text() == ""


@pytest.mark.skipif(os.name != "posix", reason="POSIX file permissions")
def test_refuse_symlink(tmp_path):
    target = tmp_path / "public.jsonl"
    target.write_text("")
    target.chmod(0o644)
    link = tmp_path / "link.jsonl"
    link.symlink_to(target)
    with pytest.raises(OSError):
        JsonlResearchRecorder(link).record(event())
    assert target.read_text() == ""


def test_wrapper_success(tmp_path):
    path = tmp_path / "events.jsonl"
    recorder = JsonlResearchRecorder(path)
    result = evaluation()

    async def success():
        return result

    assert (
        asyncio.run(
            record_evaluation(
                success,
                estimator=estimator(),
                context=context(),
                recorder=recorder,
            )
        )
        is result
    )
    recorded = ResearchEvent.model_validate_json(path.read_text())
    assert recorded.outcome == "succeeded"


def test_wrapper_failure(tmp_path):
    path = tmp_path / "events.jsonl"
    recorder = JsonlResearchRecorder(path)
    recorder.record(event())
    original = InferenceError("SECRET CUSTOMER CONTENT")

    async def failed():
        raise original

    with pytest.raises(InferenceError) as caught:
        asyncio.run(
            record_evaluation(
                failed,
                estimator=estimator(),
                context=context(),
                recorder=recorder,
            )
        )
    assert caught.value is original
    lines = path.read_text().splitlines()
    failure = ResearchEvent.model_validate_json(lines[1])
    assert failure.failure_code == "inference_failure"
    assert failure.classification is None
    assert failure.convergence is None
    assert failure.graph is None
    assert "SECRET" not in path.read_text()


def test_cancellation_is_preserved(tmp_path):
    path = tmp_path / "events.jsonl"

    async def cancelled():
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            record_evaluation(
                cancelled,
                estimator=estimator(),
                context=context(),
                recorder=JsonlResearchRecorder(path),
            )
        )
    assert (
        ResearchEvent.model_validate_json(path.read_text()).outcome
        == "cancelled"
    )


def test_recorder_failure_does_not_change_evaluation():
    class BrokenRecorder:
        def record(self, value):
            raise OSError("SECRET PATH")

    result = evaluation()

    async def success():
        return result

    with pytest.warns(
        RuntimeWarning, match="Research telemetry could not be recorded"
    ):
        assert (
            asyncio.run(
                record_evaluation(
                    success,
                    estimator=estimator(),
                    context=context(),
                    recorder=BrokenRecorder(),
                )
            )
            is result
        )


def test_constant_summary_rounding():
    assert summarize([0.1, 0.1, 0.1]).mean == pytest.approx(0.1)


def test_forged_extra_fields_never_reach_disk(tmp_path):
    path = tmp_path / "events.jsonl"
    value = event()
    value.estimator.weights["secret"] = 1.0
    with pytest.raises(ValidationError):
        JsonlResearchRecorder(path).record(value)
    assert not path.exists()


def test_multi_source_aggregates_are_not_raw_records():
    sources = {
        name: Source("web_publisher", name + ".example", "same-private-owner")
        for name in ("first", "second")
    }
    claim = Claim("service", "private-entity", "status", "secret-claim")
    observations = tuple(
        Observation(
            name,
            source,
            claim,
            datetime.now(timezone.utc),
            upstream_sources=(),
            cited_sources=(),
            parent_assertion_ids=(),
        )
        for name, source in sources.items()
    )
    pairs, _ = estimate_dependencies(
        tuple(sources.values()), observations, estimator()
    )
    graph = build_graph(
        [AssertionTriple(name, "attribute", "claim") for name in sources],
        [
            SourcePair(
                "first",
                "second",
                pairs[0].dependency,
                pairs[0].weighted_signal_coverage,
            )
        ],
    )
    result = _map_assertion_evaluation(
        infer(graph), sources, {"claim": claim}, pairs, None
    )
    value = build_event(
        context=context(),
        estimator=estimator(),
        latency_ms=1.0,
        evaluation=result,
    )
    assert value.graph.pairs == 1
    assert value.graph.edges == 2
    assert value.signals["ownership"].observable_pairs == 1
    assert value.signal_coverage.mean == pytest.approx(3 / 7)
    assert value.dependency.mean == 0.0
    assert value.effective_support.mean == 2.0
    assert "secret-claim" not in value.model_dump_json()
    assert "same-private-owner" not in value.model_dump_json()


@pytest.fixture
def clean_checkout(tmp_path):
    checkout = tmp_path / "checkout"
    subprocess.run(
        [
            "git",
            "clone",
            "--quiet",
            "--shared",
            str(Path(__file__).resolve().parents[1]),
            str(checkout),
        ],
        check=True,
    )
    return checkout


def test_checkout_provenance(clean_checkout):
    provenance = checkout_provenance(clean_checkout)
    assert provenance.state == "clean"
    assert provenance.origin == "verified_checkout"
    assert (
        provenance.revision
        == subprocess.check_output(
            ["git", "-C", str(clean_checkout), "rev-parse", "HEAD"],
            text=True,
        ).strip()
    )


@pytest.fixture
def verified_event(clean_checkout):
    provenance = checkout_provenance(clean_checkout)
    return build_event(
        context=EvaluationContext(run_id=uuid4(), implementation=provenance),
        estimator=estimator(),
        latency_ms=1.0,
        evaluation=evaluation(),
    )


def test_verified_provenance_round_trip(verified_event):
    payload = verified_event.model_dump_json()
    assert set(json.loads(payload)["context"]["implementation"]) == {
        "revision",
        "state",
        "origin",
    }
    assert "_verified_checkout" not in payload
    assert "_CHECKOUT_VERIFICATION" not in payload
    restored = ResearchEvent.model_validate_json(payload)
    assert restored.model_dump_json() == payload


def test_verified_event_recording(verified_event, tmp_path):
    payload = verified_event.model_dump_json()
    destination = tmp_path / "events.jsonl"
    JsonlResearchRecorder(destination).record(verified_event)
    assert destination.read_text() == payload + "\n"


def test_parsed_provenance_cannot_be_recorded(verified_event, tmp_path):
    payload = verified_event.model_dump_json()
    restored = ResearchEvent.model_validate_json(payload)
    destination = tmp_path / "events.jsonl"
    JsonlResearchRecorder(destination).record(verified_event)
    with pytest.raises(ValueError, match="checkout verification"):
        JsonlResearchRecorder(destination).record(restored)
    assert destination.read_text() == payload + "\n"


def test_parsed_provenance_cannot_build_event(verified_event):
    restored = ResearchEvent.model_validate_json(
        verified_event.model_dump_json()
    )
    with pytest.raises(ValueError, match="checkout verification"):
        build_event(
            context=restored.context,
            estimator=estimator(),
            latency_ms=1.0,
            evaluation=evaluation(),
        )


@pytest.mark.parametrize("tracked", [True, False])
def test_dirty_checkout_cannot_be_promoted_to_clean(clean_checkout, tracked):
    subprocess.run(
        [
            "git",
            "-C",
            str(clean_checkout),
            "config",
            "status.showUntrackedFiles",
            "no",
        ],
        check=True,
    )
    (
        clean_checkout / ("README.md" if tracked else "untracked.txt")
    ).write_text("dirty")
    provenance = checkout_provenance(clean_checkout)
    assert provenance.origin == "verified_checkout"
    assert provenance.state == "dirty"
    value = build_event(
        context=EvaluationContext(run_id=uuid4(), implementation=provenance),
        estimator=estimator(),
        latency_ms=1.0,
        evaluation=evaluation(),
    )
    assert value.context.implementation.state == "dirty"
    with pytest.raises(ValidationError, match="checkout verification"):
        EvaluationContext(
            run_id=uuid4(),
            implementation=provenance.model_copy(update={"state": "clean"}),
        )


@pytest.mark.parametrize("origin", ["unknown", "supplied"])
def test_unverified_provenance_cannot_be_promoted(origin, tmp_path):
    provenance = (
        checkout_provenance(tmp_path)
        if origin == "unknown"
        else ImplementationProvenance(
            revision="a" * 40,
            state="clean",
            origin="supplied",
        )
    )
    assert provenance.origin == origin
    build_event(
        context=EvaluationContext(run_id=uuid4(), implementation=provenance),
        estimator=estimator(),
        latency_ms=1.0,
        evaluation=evaluation(),
    )
    promoted = provenance.model_copy(
        update={
            "revision": "a" * 40,
            "state": "clean",
            "origin": "verified_checkout",
        }
    )
    with pytest.raises(ValidationError, match="checkout verification"):
        EvaluationContext(run_id=uuid4(), implementation=promoted)


@pytest.mark.parametrize("state", ["clean", "dirty", "unknown"])
def test_direct_verified_provenance_rejected(state):
    with pytest.raises(ValidationError, match="checkout verification"):
        ImplementationProvenance(
            revision="a" * 40, state=state, origin="verified_checkout"
        )


@pytest.mark.parametrize("field", ["implementation", "remote_implementation"])
def test_forged_wire_provenance_cannot_be_recorded(field, tmp_path):
    raw = json.loads(event().model_dump_json())
    raw["context"][field] = {
        "revision": "a" * 40,
        "state": "clean",
        "origin": "verified_checkout",
    }
    parsed = ResearchEvent.model_validate_json(json.dumps(raw))
    destination = tmp_path / "events.jsonl"
    with pytest.raises(ValueError, match="checkout verification"):
        JsonlResearchRecorder(destination).record(parsed)
    assert not destination.exists()
    with pytest.raises(ValueError, match="checkout verification"):
        build_event(
            context=parsed.context,
            estimator=estimator(),
            latency_ms=1.0,
            evaluation=evaluation(),
        )


@pytest.mark.parametrize(
    "recorder_error",
    [OSError, asyncio.CancelledError, KeyboardInterrupt, SystemExit],
)
@pytest.mark.parametrize("outcome", ["success", "failure", "cancelled"])
def test_recorder_baseexceptions_preserve_evaluation_outcome(
    recorder_error, outcome
):
    class BrokenRecorder:
        def record(self, value):
            raise recorder_error("PRIVATE RECORDER FAILURE")

    result = evaluation()
    original = (
        asyncio.CancelledError("original cancellation")
        if outcome == "cancelled"
        else InferenceError("original error")
    )

    async def operation():
        if outcome != "success":
            raise original
        return result

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        if outcome == "success":
            assert (
                asyncio.run(
                    record_evaluation(
                        operation,
                        estimator=estimator(),
                        context=context(),
                        recorder=BrokenRecorder(),
                    )
                )
                is result
            )
        else:
            with pytest.raises(type(original)) as caught:
                asyncio.run(
                    record_evaluation(
                        operation,
                        estimator=estimator(),
                        context=context(),
                        recorder=BrokenRecorder(),
                    )
                )
            assert caught.value is original
