from __future__ import annotations

import inspect
import json
import tempfile
from enum import IntEnum
from pathlib import Path

import pytest

from verity.linkage import (
    ENCODING_VERSION,
    HEADER_SIZE,
    MAX_LINKAGE_INPUT_SIZE,
    PROTOCOL_LABEL,
    LinkageBlindResult,
    LinkageClient,
    LinkagePurpose,
    encode_linkage_input,
)
from verity.oprf import (
    VOPRFBlindResult,
    VOPRFClient,
    VOPRFEvaluation,
    VOPRFServer,
)
from verity.serialization import (
    MAX_LINKAGE_PAYLOAD_SIZE,
    serialize_attribute,
    serialize_claim,
    serialize_source,
)


VECTOR_PATH = (
    Path(__file__).parent
    / "vectors"
    / "linkage_input_v1.json"
)
# Scalar 1 encoded as a fixed test key. Never use in production.
SERVER_KEY = b"\x01" + b"\x00" * 31


def make_server() -> VOPRFServer:
    with tempfile.TemporaryDirectory() as directory:
        private_key_file = Path(directory) / "voprf.key"
        private_key_file.write_bytes(SERVER_KEY)
        return VOPRFServer(private_key_file)


class OtherPurpose(IntEnum):
    SOURCE = 1


class RecordingClient:
    def __init__(self) -> None:
        self.blinded_inputs: list[bytes] = []
        self.finalized: list[
            tuple[bytes, bytes, VOPRFEvaluation]
        ] = []

    def blind(
        self,
        input_data: bytes,
    ) -> VOPRFBlindResult:
        self.blinded_inputs.append(input_data)
        return VOPRFBlindResult(
            blinded_element=b"b" * 32,
            client_state=b"s" * 64,
        )

    def finalize(
        self,
        *,
        input_data: bytes,
        client_state: bytes,
        evaluation: VOPRFEvaluation,
    ) -> bytes:
        self.finalized.append(
            (
                input_data,
                client_state,
                evaluation,
            )
        )
        return b"o" * 64


def load_vectors() -> list[dict[str, object]]:
    return json.loads(
        VECTOR_PATH.read_text(encoding="utf-8")
    )


def test_header() -> None:
    payload = b"canonical payload"
    encoded = encode_linkage_input(
        payload,
        LinkagePurpose.CLAIM,
    )

    assert len(PROTOCOL_LABEL) == 12
    assert HEADER_SIZE == 17
    assert encoded[:12] == PROTOCOL_LABEL
    assert encoded[12:14] == b"\x00\x01"
    assert encoded[14] == 0x03
    assert encoded[15:17] == len(payload).to_bytes(
        2,
        "big",
    )
    assert encoded[17:] == payload
    assert len(encoded) == HEADER_SIZE + len(payload)


def test_vectors() -> None:
    for vector in load_vectors():
        payload = bytes.fromhex(
            str(vector["canonical_payload_hex"])
        )
        purpose = LinkagePurpose(
            int(vector["purpose"])
        )
        version = int(vector["encoding_version"])
        expected = bytes.fromhex(
            str(vector["encoded_input_hex"])
        )
        encoded = encode_linkage_input(
            payload,
            purpose,
            version,
        )

        assert len(payload) == int.from_bytes(
            expected[15:17],
            "big",
        )
        assert len(expected) == HEADER_SIZE + len(payload)
        assert encoded == expected


def test_serializer_vectors() -> None:
    vectors = {
        vector["name"]: vector
        for vector in load_vectors()
    }
    source = serialize_source(
        "web_publisher",
        "docs.anthropic.com",
    )
    attribute = serialize_attribute(
        "service",
        "caf\u00e9",
        "display_name",
    )
    claim = serialize_claim(
        "service",
        "messages_api",
        "supports_streaming",
        True,
    )

    assert source.hex() == vectors[
        "source"
    ]["canonical_payload_hex"]
    assert attribute.hex() == vectors[
        "attribute"
    ]["canonical_payload_hex"]
    assert claim.hex() == vectors[
        "claim"
    ]["canonical_payload_hex"]


def test_purpose_separation() -> None:
    vectors = [
        vector
        for vector in load_vectors()
        if str(vector["name"]).startswith("same_")
    ]
    payloads = {
        vector["canonical_payload_hex"]
        for vector in vectors
    }
    encoded = {
        vector["encoded_input_hex"]
        for vector in vectors
    }

    assert len(payloads) == 1
    assert len(encoded) == 3


def test_big_endian_fields() -> None:
    payload = b"x" * 258
    encoded = encode_linkage_input(
        payload,
        LinkagePurpose.ATTRIBUTE,
    )

    assert encoded[12:14] == b"\x00\x01"
    assert encoded[15:17] == b"\x01\x02"


def test_empty_payload() -> None:
    with pytest.raises(ValueError):
        encode_linkage_input(
            b"",
            LinkagePurpose.SOURCE,
        )


def test_payload_limit() -> None:
    payload = b"x" * MAX_LINKAGE_PAYLOAD_SIZE
    encoded = encode_linkage_input(
        payload,
        LinkagePurpose.SOURCE,
    )

    assert len(encoded) == MAX_LINKAGE_INPUT_SIZE

    with pytest.raises(ValueError):
        encode_linkage_input(
            payload + b"x",
            LinkagePurpose.SOURCE,
        )


@pytest.mark.parametrize(
    "version",
    [
        0,
        2,
        -1,
        65_536,
    ],
)
def test_unsupported_version(version: int) -> None:
    with pytest.raises(ValueError):
        encode_linkage_input(
            b"payload",
            LinkagePurpose.SOURCE,
            version,
        )


@pytest.mark.parametrize(
    "version",
    [
        True,
        False,
        1.0,
        "1",
        None,
    ],
)
def test_invalid_version(version: object) -> None:
    with pytest.raises(TypeError):
        encode_linkage_input(
            b"payload",
            LinkagePurpose.SOURCE,
            version,
        )


@pytest.mark.parametrize(
    "purpose",
    [
        0,
        1,
        4,
        OtherPurpose.SOURCE,
        "source",
        None,
    ],
)
def test_invalid_purpose(purpose: object) -> None:
    with pytest.raises(TypeError):
        encode_linkage_input(
            b"payload",
            purpose,
        )


@pytest.mark.parametrize(
    "payload",
    [
        bytearray(b"payload"),
        memoryview(b"payload"),
        "payload",
        ["payload"],
        None,
    ],
)
def test_invalid_payload(payload: object) -> None:
    with pytest.raises(TypeError):
        encode_linkage_input(
            payload,
            LinkagePurpose.SOURCE,
        )


def test_payload_preserved() -> None:
    payload = b"\x00\xff \ncanonical\x00"
    encoded = encode_linkage_input(
        payload,
        LinkagePurpose.CLAIM,
    )

    assert encoded[HEADER_SIZE:] == payload


def test_blind_result_repr() -> None:
    result = LinkageBlindResult(
        blinded_element=b"visible element",
        purpose=LinkagePurpose.SOURCE,
        encoding_version=ENCODING_VERSION,
        _encoded_input=b"private input",
        _client_state=b"private state",
    )

    assert "private input" not in repr(result)
    assert "private state" not in repr(result)
    assert "private input" not in str(result)
    assert "private state" not in str(result)
    assert "visible element" in repr(result)
    assert "LinkagePurpose.SOURCE" in repr(result)
    assert "encoding_version=1" in repr(result)


def test_blind_methods() -> None:
    recording = RecordingClient()
    client = LinkageClient(recording)

    source = client.blind_source(
        "web_publisher",
        "docs.anthropic.com",
    )
    attribute = client.blind_attribute(
        "service",
        "worker",
        "status",
    )
    claim = client.blind_claim(
        "service",
        "worker",
        "status",
        True,
    )

    assert recording.blinded_inputs == [
        encode_linkage_input(
            serialize_source(
                "web_publisher",
                "docs.anthropic.com",
            ),
            LinkagePurpose.SOURCE,
        ),
        encode_linkage_input(
            serialize_attribute(
                "service",
                "worker",
                "status",
            ),
            LinkagePurpose.ATTRIBUTE,
        ),
        encode_linkage_input(
            serialize_claim(
                "service",
                "worker",
                "status",
                True,
            ),
            LinkagePurpose.CLAIM,
        ),
    ]
    assert source.purpose is LinkagePurpose.SOURCE
    assert attribute.purpose is LinkagePurpose.ATTRIBUTE
    assert claim.purpose is LinkagePurpose.CLAIM


def test_finalize() -> None:
    recording = RecordingClient()
    client = LinkageClient(recording)
    result = client.blind_claim(
        "service",
        "worker",
        "status",
        True,
    )
    evaluation = VOPRFEvaluation(
        evaluated_element=b"e" * 32,
        proof=b"p" * 64,
    )

    output = client.finalize(
        result,
        evaluation,
    )

    assert output == b"o" * 64
    assert recording.finalized == [
        (
            recording.blinded_inputs[0],
            b"s" * 64,
            evaluation,
        )
    ]


def test_finalize_signature() -> None:
    parameters = inspect.signature(
        LinkageClient.finalize
    ).parameters

    assert tuple(parameters) == (
        "self",
        "result",
        "evaluation",
    )


def test_round_trip() -> None:
    server = make_server()
    client = LinkageClient(
        VOPRFClient(server.public_key)
    )

    first = client.blind_source(
        "web_publisher",
        "docs.anthropic.com",
    )
    first_evaluation = server.evaluate(
        first.blinded_element
    )
    first_output = client.finalize(
        first,
        first_evaluation,
    )

    second = client.blind_source(
        "web_publisher",
        "docs.anthropic.com",
    )
    second_evaluation = server.evaluate(
        second.blinded_element
    )
    second_output = client.finalize(
        second,
        second_evaluation,
    )

    assert first.blinded_element != second.blinded_element
    assert first_output == second_output


def test_purpose_changes_output() -> None:
    server = make_server()
    client = VOPRFClient(server.public_key)
    payload = b'{"value":true}'
    outputs = []

    for purpose in LinkagePurpose:
        encoded = encode_linkage_input(
            payload,
            purpose,
        )
        result = client.blind(encoded)
        evaluated = server.evaluate(
            result.blinded_element
        )
        outputs.append(
            client.finalize(
                input_data=encoded,
                client_state=result.client_state,
                evaluation=evaluated,
            )
        )

    assert len(set(outputs)) == 3
