from __future__ import annotations

import asyncio
from dataclasses import replace
import json
from pathlib import Path
import threading

import pytest

import verity.tools.infer_credibility as tool_module
from verity.base64url import encode_unpadded
from verity.config import DeploymentState
from verity.inference import InferenceError
from verity.models import (
    EvaluateVOPRFRequest,
    InferCredibilityRequest,
    InferCredibilityResponse,
)
from verity.oprf import VOPRFEvaluation
from verity.tools.evaluate_voprf import EvaluationService
from verity.tools.infer_credibility import InferenceService
from verity.transport.mcp import create_server


DEPLOYMENT_ID = (
    "urn:uuid:8d96fc18-f40f-4ec7-8ae8-f3711d88b741"
)
VECTOR_PATH = (
    Path(__file__).parent
    / "vectors"
    / "inference_v1.json"
)


def token(value):
    return encode_unpadded(
        value.to_bytes(64, "big"),
        expected_length=64,
    )


SOURCE_A = token(1)
SOURCE_B = token(2)
SOURCE_C = token(3)
ATTRIBUTE_A = token(101)
ATTRIBUTE_B = token(102)
CLAIM_A = token(201)
CLAIM_B = token(202)


def make_state(
    *,
    server=None,
    concurrency=1,
    timeout_ms=1_000,
):
    return DeploymentState(
        deployment_id=DEPLOYMENT_ID,
        voprf_key_version=1,
        configuration_fingerprint="f" * 64,
        voprf_server=server or object(),
        inference_max_concurrency=concurrency,
        inference_timeout_ms=timeout_ms,
    )


def values(**changes):
    result = {
        "protocol_version": "v1",
        "deployment_id": DEPLOYMENT_ID,
        "voprf_key_version": 1,
        "voprf_mode": "voprf",
        "voprf_ciphersuite": "ristretto255-SHA512",
        "linkage_encoding_version": 1,
        "assertions": [
            {
                "source_id": SOURCE_A,
                "attribute_id": ATTRIBUTE_A,
                "claim_id": CLAIM_A,
            }
        ],
        "source_pairs": [],
    }
    result.update(changes)
    return result


def request(**changes):
    return InferCredibilityRequest.model_validate(values(**changes))


def code(result):
    assert result.isError
    assert result.structuredContent is not None
    assert set(result.structuredContent) == {
        "message",
        "verity_code",
    }
    assert json.loads(result.content[0].text) == result.structuredContent
    return result.structuredContent["verity_code"]


def golden_values():
    vector = json.loads(VECTOR_PATH.read_text(encoding="utf-8"))
    source_ids = sorted({
        item["source_id"]
        for item in vector["assertions"]
    })
    attribute_ids = sorted({
        item["attribute_id"]
        for item in vector["assertions"]
    })
    claim_ids = sorted({
        item["claim_id"]
        for item in vector["assertions"]
    })
    mapping = {
        **{
            value: token(index + 1)
            for index, value in enumerate(source_ids)
        },
        **{
            value: token(index + 101)
            for index, value in enumerate(attribute_ids)
        },
        **{
            value: token(index + 201)
            for index, value in enumerate(claim_ids)
        },
    }
    assertions = sorted(
        (
            {
                "source_id": mapping[item["source_id"]],
                "attribute_id": mapping[item["attribute_id"]],
                "claim_id": mapping[item["claim_id"]],
            }
            for item in vector["assertions"]
        ),
        key=lambda item: (
            item["source_id"],
            item["attribute_id"],
            item["claim_id"],
        ),
    )
    source_pairs = sorted(
        (
            {
                "source_a_id": mapping[item["source_a_id"]],
                "source_b_id": mapping[item["source_b_id"]],
                "dependency": item["dependency"],
                "weighted_signal_coverage": (
                    item["weighted_signal_coverage"]
                ),
            }
            for item in vector["source_pairs"]
        ),
        key=lambda item: (
            item["source_a_id"],
            item["source_b_id"],
        ),
    )
    return values(
        assertions=assertions,
        source_pairs=source_pairs,
    )


def test_schema():
    schema = InferCredibilityRequest.model_json_schema()
    fields = {
        "protocol_version",
        "deployment_id",
        "voprf_key_version",
        "voprf_mode",
        "voprf_ciphersuite",
        "linkage_encoding_version",
        "assertions",
        "source_pairs",
    }
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == fields
    assert set(schema["required"]) == fields
    assert schema["$defs"]["Assertion"]["additionalProperties"] is False
    assert schema["$defs"]["SourcePair"]["additionalProperties"] is False

    response_schema = InferCredibilityResponse.model_json_schema()
    assert response_schema["additionalProperties"] is False
    assert set(response_schema["required"]) == {
        "protocol_version",
        "deployment_id",
        "voprf_key_version",
        "voprf_mode",
        "voprf_ciphersuite",
        "linkage_encoding_version",
        "summary",
        "source_credibility",
        "claim_support",
        "metadata",
    }
    for definition in response_schema["$defs"].values():
        assert definition["additionalProperties"] is False
        assert set(definition["required"]) == set(
            definition["properties"]
        )


@pytest.mark.parametrize(
    "change",
    [
        {"unknown": "value"},
        {"voprf_key_version": "1"},
        {"voprf_key_version": True},
        {"assertions": "not-a-list"},
        {"assertions": [{
            "source_id": SOURCE_A,
            "attribute_id": ATTRIBUTE_A,
            "claim_id": CLAIM_A,
            "unknown": "value",
        }]},
        {"source_pairs": [{
            "source_a_id": SOURCE_A,
            "source_b_id": SOURCE_B,
            "dependency": "0.5",
            "weighted_signal_coverage": 1.0,
        }]},
        {"source_pairs": [{
            "source_a_id": SOURCE_A,
            "source_b_id": SOURCE_B,
            "dependency": True,
            "weighted_signal_coverage": 1.0,
        }]},
    ],
)
def test_strict(change):
    data = values()
    data.update(change)
    with pytest.raises(ValueError):
        InferCredibilityRequest.model_validate(data)


def test_missing():
    data = values()
    del data["protocol_version"]
    with pytest.raises(ValueError):
        InferCredibilityRequest.model_validate(data)


def test_metadata():
    async def run():
        service = InferenceService(make_state())
        mismatches = [
            ("protocol_version", "v2", "unsupported_protocol_version"),
            (
                "deployment_id",
                "urn:uuid:01234567-89ab-cdef-0123-456789abcdef",
                "deployment_mismatch",
            ),
            ("voprf_key_version", 2, "voprf_key_version_mismatch"),
            ("voprf_mode", "oprf", "unsupported_voprf_mode"),
            (
                "voprf_ciphersuite",
                "other",
                "unsupported_voprf_ciphersuite",
            ),
            (
                "linkage_encoding_version",
                2,
                "unsupported_linkage_encoding_version",
            ),
        ]
        try:
            for index, (field, value, expected) in enumerate(mismatches):
                changes = {
                    later_field: later_value
                    for later_field, later_value, _ in mismatches[index:]
                }
                changes[field] = value
                assert code(
                    await service.evaluate(request(**changes))
                ) == expected
        finally:
            service.close()

    asyncio.run(run())


def test_metadata_precedes_graph():
    async def run():
        service = InferenceService(make_state())
        try:
            result = await service.evaluate(request(
                protocol_version="v2",
                assertions=[],
            ))
            assert code(result) == "unsupported_protocol_version"
        finally:
            service.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "malformed",
    [
        "",
        "A" * 85,
        "A" * 87,
        SOURCE_A + "=",
        SOURCE_A[:-1] + "+",
        SOURCE_A[:-1] + " ",
    ],
)
def test_tokens(malformed):
    async def run():
        service = InferenceService(make_state())
        try:
            result = await service.evaluate(request(
                assertions=[{
                    "source_id": malformed,
                    "attribute_id": ATTRIBUTE_A,
                    "claim_id": CLAIM_A,
                }],
            ))
            assert code(result) == "invalid_graph"
        finally:
            service.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "field",
    ["source_id", "attribute_id", "claim_id"],
)
def test_assertion_token_fields(field):
    async def run():
        assertion = {
            "source_id": SOURCE_A,
            "attribute_id": ATTRIBUTE_A,
            "claim_id": CLAIM_A,
        }
        assertion[field] += "="
        service = InferenceService(make_state())
        try:
            assert code(await service.evaluate(request(
                assertions=[assertion],
            ))) == "invalid_graph"
        finally:
            service.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "assertions",
    [
        [],
        [
            {
                "source_id": SOURCE_B,
                "attribute_id": ATTRIBUTE_A,
                "claim_id": CLAIM_A,
            },
            {
                "source_id": SOURCE_A,
                "attribute_id": ATTRIBUTE_A,
                "claim_id": CLAIM_A,
            },
        ],
        [
            {
                "source_id": SOURCE_A,
                "attribute_id": ATTRIBUTE_A,
                "claim_id": CLAIM_A,
            },
            {
                "source_id": SOURCE_A,
                "attribute_id": ATTRIBUTE_A,
                "claim_id": CLAIM_A,
            },
        ],
        [
            {
                "source_id": SOURCE_A,
                "attribute_id": ATTRIBUTE_A,
                "claim_id": CLAIM_A,
            },
            {
                "source_id": SOURCE_B,
                "attribute_id": ATTRIBUTE_B,
                "claim_id": CLAIM_A,
            },
        ],
        [
            {
                "source_id": SOURCE_A,
                "attribute_id": ATTRIBUTE_A,
                "claim_id": CLAIM_A,
            },
            {
                "source_id": SOURCE_A,
                "attribute_id": ATTRIBUTE_A,
                "claim_id": CLAIM_B,
            },
        ],
    ],
)
def test_assertions(assertions):
    async def run():
        service = InferenceService(make_state())
        try:
            result = await service.evaluate(request(
                assertions=assertions,
                source_pairs=[] if len({
                    item["source_id"] for item in assertions
                }) < 2 else [{
                    "source_a_id": SOURCE_A,
                    "source_b_id": SOURCE_B,
                    "dependency": 0.0,
                    "weighted_signal_coverage": 0.0,
                }],
            ))
            assert code(result) == "invalid_graph"
        finally:
            service.close()

    asyncio.run(run())


def pair_request(source_pairs):
    return request(
        assertions=[
            {
                "source_id": SOURCE_A,
                "attribute_id": ATTRIBUTE_A,
                "claim_id": CLAIM_A,
            },
            {
                "source_id": SOURCE_B,
                "attribute_id": ATTRIBUTE_A,
                "claim_id": CLAIM_A,
            },
            {
                "source_id": SOURCE_C,
                "attribute_id": ATTRIBUTE_A,
                "claim_id": CLAIM_A,
            },
        ],
        source_pairs=source_pairs,
    )


def canonical_pairs():
    return [
        {
            "source_a_id": SOURCE_A,
            "source_b_id": SOURCE_B,
            "dependency": 0.0,
            "weighted_signal_coverage": 0.0,
        },
        {
            "source_a_id": SOURCE_A,
            "source_b_id": SOURCE_C,
            "dependency": 0.0,
            "weighted_signal_coverage": 0.0,
        },
        {
            "source_a_id": SOURCE_B,
            "source_b_id": SOURCE_C,
            "dependency": 0.0,
            "weighted_signal_coverage": 0.0,
        },
    ]


@pytest.mark.parametrize(
    "source_pairs",
    [
        canonical_pairs()[:-1],
        [*canonical_pairs(), canonical_pairs()[0]],
        [canonical_pairs()[1], canonical_pairs()[0], canonical_pairs()[2]],
        [canonical_pairs()[0], canonical_pairs()[0], canonical_pairs()[2]],
        [
            {
                **canonical_pairs()[0],
                "source_a_id": SOURCE_B,
                "source_b_id": SOURCE_A,
            },
            canonical_pairs()[1],
            canonical_pairs()[2],
        ],
        [
            {**canonical_pairs()[0], "source_b_id": SOURCE_A},
            canonical_pairs()[1],
            canonical_pairs()[2],
        ],
        [
            {**canonical_pairs()[0], "source_b_id": token(4)},
            canonical_pairs()[1],
            canonical_pairs()[2],
        ],
    ],
)
def test_pairs(source_pairs):
    async def run():
        service = InferenceService(make_state())
        try:
            assert code(
                await service.evaluate(pair_request(source_pairs))
            ) == "invalid_graph"
        finally:
            service.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("dependency", -0.1),
        ("dependency", 1.1),
        ("dependency", float("inf")),
        ("dependency", float("nan")),
        ("weighted_signal_coverage", -0.1),
        ("weighted_signal_coverage", 1.1),
        ("weighted_signal_coverage", float("inf")),
        ("weighted_signal_coverage", float("nan")),
    ],
)
def test_pair_values(field, value):
    async def run():
        pairs = canonical_pairs()
        pairs[0] = {**pairs[0], field: value}
        service = InferenceService(make_state())
        try:
            assert code(
                await service.evaluate(pair_request(pairs))
            ) == "invalid_graph"
        finally:
            service.close()

    asyncio.run(run())


def test_pair_token():
    async def run():
        pairs = canonical_pairs()
        pairs[0] = {
            **pairs[0],
            "source_a_id": pairs[0]["source_a_id"] + "=",
        }
        service = InferenceService(make_state())
        try:
            assert code(
                await service.evaluate(pair_request(pairs))
            ) == "invalid_graph"
        finally:
            service.close()

    asyncio.run(run())


def test_bounds():
    async def run():
        service = InferenceService(make_state())
        too_many = [
            {
                "source_id": SOURCE_A,
                "attribute_id": token(index + 1_000),
                "claim_id": token(index + 10_000),
            }
            for index in range(4097)
        ]
        too_many_sources = [
            {
                "source_id": token(index + 1),
                "attribute_id": token(index + 1_000),
                "claim_id": token(index + 10_000),
            }
            for index in range(65)
        ]
        too_many_attributes = [
            {
                "source_id": SOURCE_A,
                "attribute_id": token(index + 1_000),
                "claim_id": token(index + 10_000),
            }
            for index in range(2049)
        ]
        try:
            for assertions in (
                too_many,
                too_many_sources,
                too_many_attributes,
            ):
                assert code(await service.evaluate(request(
                    assertions=assertions,
                ))) == "invalid_graph"
        finally:
            service.close()

    asyncio.run(run())


def test_golden():
    async def run():
        service = InferenceService(make_state())
        try:
            first = await service.evaluate(
                InferCredibilityRequest.model_validate(golden_values())
            )
            second = await service.evaluate(
                InferCredibilityRequest.model_validate(golden_values())
            )
            assert not first.isError
            assert first.structuredContent == second.structuredContent
            content = first.structuredContent
            assert content is not None
            assert content["summary"] == {
                "source_count": 5,
                "claim_count": 6,
                "assertion_count": 15,
            }
            assert content["metadata"]["iterations"] == 9
            assert content["metadata"]["converged"] is True
            assert "computation_time_ms" not in content["metadata"]
            encoded = json.dumps(content)
            for forbidden in (
                "dependency_clusters",
                "cluster_threshold",
                "provenance",
                "raw_signals",
                "source-a",
                "claim-a",
            ):
                assert forbidden not in encoded
        finally:
            service.close()

    asyncio.run(run())


def test_inference_failure(monkeypatch):
    def fail(_graph):
        raise InferenceError("private detail")

    monkeypatch.setattr(tool_module, "infer", fail)

    async def run():
        service = InferenceService(make_state())
        try:
            result = await service.evaluate(request())
            assert code(result) == "inference_failed"
            assert "private detail" not in result.content[0].text
        finally:
            service.close()

    asyncio.run(run())


def test_invalid_output(monkeypatch):
    original = tool_module.infer

    def invalid(graph):
        result = original(graph)
        return replace(
            result,
            metadata=replace(
                result.metadata,
                maximum_credibility_delta=float("nan"),
            ),
        )

    monkeypatch.setattr(tool_module, "infer", invalid)

    async def run():
        service = InferenceService(make_state())
        try:
            assert code(
                await service.evaluate(request())
            ) == "inference_failed"
        finally:
            service.close()

    asyncio.run(run())


def test_internal_failure(monkeypatch):
    def fail(_graph):
        raise RuntimeError("secret infrastructure detail")

    monkeypatch.setattr(tool_module, "infer", fail)

    async def run():
        service = InferenceService(make_state())
        try:
            result = await service.evaluate(request())
            assert code(result) == "internal_error"
            assert "secret infrastructure detail" not in result.content[0].text
        finally:
            service.close()

    asyncio.run(run())


def test_overload(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    original = tool_module.infer

    def run_inference(graph):
        started.set()
        release.wait(timeout=5)
        return original(graph)

    monkeypatch.setattr(tool_module, "infer", run_inference)

    async def run():
        service = InferenceService(make_state())
        try:
            first = asyncio.create_task(service.evaluate(request()))
            await asyncio.to_thread(started.wait, 1)
            assert code(await service.evaluate(request())) == "server_busy"
            release.set()
            assert not (await first).isError
            assert not (await service.evaluate(request())).isError
        finally:
            release.set()
            service.close()

    asyncio.run(run())


def test_timeout(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    original = tool_module.infer

    def run_inference(graph):
        started.set()
        release.wait(timeout=5)
        return original(graph)

    monkeypatch.setattr(tool_module, "infer", run_inference)

    async def run():
        service = InferenceService(make_state(timeout_ms=10))
        try:
            assert code(await service.evaluate(request())) == "request_timeout"
            assert code(await service.evaluate(request())) == "server_busy"
            release.set()
            for _ in range(100):
                result = await service.evaluate(request())
                if not result.isError:
                    break
                assert code(result) == "server_busy"
                await asyncio.sleep(0.01)
            else:
                raise AssertionError("inference capacity was not released")
        finally:
            release.set()
            service.close()

    asyncio.run(run())


def test_cancellation(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    original = tool_module.infer

    def run_inference(graph):
        started.set()
        release.wait(timeout=5)
        return original(graph)

    monkeypatch.setattr(tool_module, "infer", run_inference)

    async def run():
        service = InferenceService(make_state())
        try:
            task = asyncio.create_task(service.evaluate(request()))
            await asyncio.to_thread(started.wait, 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert code(await service.evaluate(request())) == "server_busy"
            release.set()
        finally:
            release.set()
            service.close()

    asyncio.run(run())


def test_shutdown(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    original = tool_module.infer

    def run_inference(graph):
        started.set()
        release.wait(timeout=5)
        return original(graph)

    monkeypatch.setattr(tool_module, "infer", run_inference)

    async def run():
        service = InferenceService(make_state())
        task = asyncio.create_task(service.evaluate(request()))
        await asyncio.to_thread(started.wait, 1)
        closing = asyncio.create_task(asyncio.to_thread(service.close))
        await asyncio.sleep(0.01)
        assert not closing.done()
        release.set()
        await closing
        assert not (await task).isError
        assert code(await service.evaluate(request())) == "server_busy"

    asyncio.run(run())


class BlockingVOPRF:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()

    def evaluate(self, _blinded_element):
        self.started.set()
        self.release.wait(timeout=5)
        return VOPRFEvaluation(
            evaluated_element=b"e" * 32,
            proof=b"p" * 64,
        )


def test_independent_capacity(monkeypatch):
    voprf = BlockingVOPRF()
    inference_started = threading.Event()
    inference_release = threading.Event()
    original = tool_module.infer

    def run_inference(graph):
        inference_started.set()
        inference_release.wait(timeout=5)
        return original(graph)

    monkeypatch.setattr(tool_module, "infer", run_inference)

    async def run():
        state = make_state(server=voprf)
        evaluation = EvaluationService(state)
        inference = InferenceService(state)
        evaluation_request = EvaluateVOPRFRequest(
            protocol_version="v1",
            deployment_id=DEPLOYMENT_ID,
            voprf_key_version=1,
            voprf_mode="voprf",
            voprf_ciphersuite="ristretto255-SHA512",
            linkage_encoding_version=1,
            blinded_element=encode_unpadded(
                b"b" * 32,
                expected_length=32,
            ),
        )
        try:
            first = asyncio.create_task(inference.evaluate(request()))
            second = asyncio.create_task(evaluation.evaluate(evaluation_request))
            await asyncio.to_thread(inference_started.wait, 1)
            await asyncio.to_thread(voprf.started.wait, 1)
            assert code(await inference.evaluate(request())) == "server_busy"
            assert code(await evaluation.evaluate(evaluation_request)) == "server_busy"
            inference_release.set()
            voprf.release.set()
            assert not (await first).isError
            assert not (await second).isError
        finally:
            inference_release.set()
            voprf.release.set()
            inference.close()
            evaluation.close()

    asyncio.run(run())


def test_discovery():
    server = create_server(make_state())
    tool = server._tool_manager.get_tool("infer_credibility")

    assert tool is not None
    assert tool.parameters == InferCredibilityRequest.model_json_schema()


def test_fastmcp_validation():
    async def run():
        server = create_server(make_state())
        malformed = [
            {**values(), "unknown": "value"},
            {
                key: value
                for key, value in values().items()
                if key != "protocol_version"
            },
            {**values(), "voprf_key_version": "1"},
            {
                **values(),
                "assertions": [{
                    **values()["assertions"][0],
                    "unknown": "value",
                }],
            },
        ]
        for arguments in malformed:
            result = await server.call_tool(
                "infer_credibility",
                arguments,
            )
            assert code(result) == "invalid_request"

    asyncio.run(run())
