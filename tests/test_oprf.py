from __future__ import annotations

from daemon_support import VOPRFServer

import copy
import os
import pickle
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import omneum_oprf
from hypothesis import given, settings, strategies as st

from omneum.oprf import (
    InvalidBlindedElementError,
    OPRFProtocolError,
    VOPRFBlindResult,
    VOPRFClient,
    VOPRFEvaluation,
)


INPUT_DATA = b"test input"
# Scalar 1 encoded as a fixed test key. Never use in production.
SERVER_KEY = b"\x01" + b"\x00" * 31
SCALAR_ORDER = bytes.fromhex(
    "edd3f55c1a631258d69cf7a2def9de14"
    "00000000000000000000000000000010"
)
SCALAR_ORDER_VALUE = int.from_bytes(SCALAR_ORDER, "little")
# Daemon-backed property tests disable deadlines to include process startup.
INPUTS = st.binary(min_size=1, max_size=128)
KEYS = st.integers(
    min_value=1,
    max_value=SCALAR_ORDER_VALUE - 1,
).map(lambda value: value.to_bytes(32, "little"))
INPUT_PAIRS = st.binary(max_size=127).map(
    lambda value: (value + b"\x00", value + b"\x01")
)
KEY_PAIRS = st.integers(
    min_value=1,
    max_value=SCALAR_ORDER_VALUE - 2,
).flatmap(
    lambda first: st.integers(
        min_value=first + 1,
        max_value=SCALAR_ORDER_VALUE - 1,
    ).map(
        lambda second: (
            first.to_bytes(32, "little"),
            second.to_bytes(32, "little"),
        )
    )
)
INVALID_ELEMENTS = st.one_of(
    st.binary(max_size=31),
    st.binary(min_size=33, max_size=64),
)
INVALID_WIDE_VALUES = st.one_of(
    st.binary(max_size=63),
    st.binary(min_size=65, max_size=96),
)


class FakeBackend:
    def __init__(
        self,
        *,
        blind_result: VOPRFBlindResult | None = None,
        evaluation: VOPRFEvaluation | None = None,
        public_key: bytes = b"p" * 32,
        output: bytes = b"o" * 64,
    ) -> None:
        self.blind_result = blind_result or VOPRFBlindResult(
            blinded_element=b"b" * 32,
            client_state=b"s" * 64,
        )
        self.evaluation = evaluation or VOPRFEvaluation(
            evaluated_element=b"e" * 32,
            proof=b"r" * 64,
        )
        self.public_key = public_key
        self.output = output

    def blind(
        self,
        input_data: bytes,
    ) -> VOPRFBlindResult:
        return self.blind_result

    def load_server(
        self,
        private_key_file: str,
    ) -> FakeBackend:
        return self

    def validate_public_key(
        self,
        server_public_key: bytes,
    ) -> None:
        return None

    def evaluate(
        self,
        blinded_element: bytes,
    ) -> VOPRFEvaluation:
        return self.evaluation

    def finalize(
        self,
        input_data: bytes,
        client_state: bytes,
        evaluation: VOPRFEvaluation,
        server_public_key: bytes,
    ) -> bytes:
        return self.output


def make_server(
    server_key: bytes = SERVER_KEY,
) -> VOPRFServer:
    with tempfile.TemporaryDirectory() as directory:
        private_key_file = Path(directory) / "voprf.key"
        private_key_file.write_bytes(server_key)
        return VOPRFServer(private_key_file)


def make_round(
    server_key: bytes = SERVER_KEY,
) -> tuple[
    VOPRFClient,
    VOPRFBlindResult,
    VOPRFEvaluation,
]:
    server = make_server(server_key)
    client = VOPRFClient(server.public_key)
    blind_result = client.blind(INPUT_DATA)
    evaluation = server.evaluate(
        blind_result.blinded_element
    )
    return client, server, blind_result, evaluation


def test_round_trip() -> None:
    client, server, blind_result, evaluation = make_round()
    output = client.finalize(
        input_data=INPUT_DATA,
        client_state=blind_result.client_state,
        evaluation=evaluation,
    )

    assert len(server.public_key) == 32
    assert len(blind_result.blinded_element) == 32
    assert len(blind_result.client_state) == 64
    assert len(evaluation.evaluated_element) == 32
    assert len(evaluation.proof) == 64
    assert len(output) == 64


def test_repeated_input() -> None:
    server = make_server()
    client = VOPRFClient(server.public_key)

    first_blind = client.blind(INPUT_DATA)
    first_evaluation = server.evaluate(
        first_blind.blinded_element
    )
    first_output = client.finalize(
        input_data=INPUT_DATA,
        client_state=first_blind.client_state,
        evaluation=first_evaluation,
    )

    second_blind = client.blind(INPUT_DATA)
    second_evaluation = server.evaluate(
        second_blind.blinded_element
    )
    second_output = client.finalize(
        input_data=INPUT_DATA,
        client_state=second_blind.client_state,
        evaluation=second_evaluation,
    )

    assert first_blind.blinded_element != (
        second_blind.blinded_element
    )
    assert first_evaluation.proof != second_evaluation.proof
    assert first_output == second_output


def test_concurrent_server_context() -> None:
    server = make_server()
    client = VOPRFClient(server.public_key)
    inputs = [
        f"concurrent-{index}".encode("ascii")
        for index in range(16)
    ]
    blinds = [
        client.blind(input_data)
        for input_data in inputs
    ]

    with ThreadPoolExecutor(max_workers=4) as executor:
        evaluations = list(
            executor.map(
                server.evaluate,
                [
                    blind.blinded_element
                    for blind in blinds
                ],
            )
        )

    for input_data, blind, evaluation in zip(
        inputs,
        blinds,
        evaluations,
        strict=True,
    ):
        assert len(
            client.finalize(
                input_data=input_data,
                client_state=blind.client_state,
                evaluation=evaluation,
            )
        ) == 64


def test_server_context() -> None:
    # Production extension must have no key-bearing server/provisioning API.
    for name in ("_VOPRFServerContext", "provision_server_key", "derive_public_key", "evaluate"):
        assert not hasattr(omneum_oprf, name)
    from omneum.oprf import NativeVOPRFBackend
    assert not hasattr(NativeVOPRFBackend, "load_server")


def test_server_rejects_key_bytes() -> None:
    with pytest.raises(TypeError):
        VOPRFServer(SERVER_KEY)



def test_blind_result_repr() -> None:
    result = VOPRFBlindResult(
        blinded_element=b"visible blinded element",
        client_state=b"private client state",
    )

    assert "private client state" not in repr(result)
    assert "private client state" not in str(result)
    assert "visible blinded element" in repr(result)
    assert "visible blinded element" in str(result)


@pytest.mark.parametrize("field", ["element", "state"])
@pytest.mark.parametrize("length", [31, 33])
def test_invalid_blind_result(
    field: str,
    length: int,
) -> None:
    element = b"b" * 32
    state = b"s" * 64
    if field == "element":
        element = b"x" * length
    else:
        state = b"x" * (63 if length == 31 else 65)
    backend = FakeBackend(
        blind_result=VOPRFBlindResult(
            element,
            state,
        )
    )
    client = VOPRFClient(b"p" * 32, backend)

    with pytest.raises(OPRFProtocolError):
        client.blind(INPUT_DATA)


@pytest.mark.parametrize("field", ["element", "proof"])
@pytest.mark.parametrize("length", [31, 33])
def test_invalid_evaluation_result(
    field: str,
    length: int,
) -> None:
    element = b"e" * 32
    proof = b"p" * 64
    if field == "element":
        element = b"x" * length
    else:
        proof = b"x" * (63 if length == 31 else 65)
    backend = FakeBackend(
        evaluation=VOPRFEvaluation(
            element,
            proof,
        )
    )
    server = VOPRFServer("unused", backend)

    with pytest.raises(OPRFProtocolError):
        server.evaluate(b"b" * 32)


@pytest.mark.parametrize("length", [31, 33])
def test_invalid_derived_public_key(length: int) -> None:
    backend = FakeBackend(
        public_key=b"x" * length
    )

    with pytest.raises(OPRFProtocolError):
        VOPRFServer("unused", backend)


@pytest.mark.parametrize("length", [63, 65])
def test_invalid_output(length: int) -> None:
    backend = FakeBackend(
        output=b"x" * length
    )
    client = VOPRFClient(b"p" * 32, backend)

    with pytest.raises(OPRFProtocolError):
        client.finalize(
            input_data=INPUT_DATA,
            client_state=b"s" * 64,
            evaluation=VOPRFEvaluation(
                b"e" * 32,
                b"p" * 64,
            ),
        )


@pytest.mark.parametrize("length", [31, 33])
def test_invalid_blinded_element(length: int) -> None:
    server = make_server()

    with pytest.raises(ValueError):
        server.evaluate(b"x" * length)


@pytest.mark.parametrize(
    "blinded_element",
    [
        b"\x00" * 32,
        b"\xff" * 32,
    ],
)
def test_malformed_blinded_element(
    blinded_element: bytes,
) -> None:
    server = make_server()

    with pytest.raises(InvalidBlindedElementError):
        server.evaluate(blinded_element)


@pytest.mark.parametrize("length", [63, 65])
def test_invalid_client_state(length: int) -> None:
    client, _, _, evaluation = make_round()

    with pytest.raises(ValueError):
        client.finalize(
            input_data=INPUT_DATA,
            client_state=b"x" * length,
            evaluation=evaluation,
        )


@pytest.mark.parametrize("length", [31, 33])
def test_invalid_evaluated_element(length: int) -> None:
    client, _, blind_result, evaluation = make_round()

    with pytest.raises(ValueError):
        client.finalize(
            input_data=INPUT_DATA,
            client_state=blind_result.client_state,
            evaluation=VOPRFEvaluation(
                b"x" * length,
                evaluation.proof,
            ),
        )


@pytest.mark.parametrize("length", [63, 65])
def test_invalid_proof(length: int) -> None:
    client, _, blind_result, evaluation = make_round()

    with pytest.raises(ValueError):
        client.finalize(
            input_data=INPUT_DATA,
            client_state=blind_result.client_state,
            evaluation=VOPRFEvaluation(
                evaluation.evaluated_element,
                b"x" * length,
            ),
        )


@pytest.mark.parametrize("length", [31, 33])
def test_invalid_public_key_length(length: int) -> None:
    with pytest.raises(ValueError):
        VOPRFClient(b"x" * length)


@pytest.mark.parametrize(
    "public_key",
    [
        b"\x00" * 32,
        b"\xff" * 32,
    ],
)
def test_invalid_public_key(public_key: bytes) -> None:
    with pytest.raises(
        OPRFProtocolError,
        match="Malformed RFC 9497 VOPRF public key",
    ):
        VOPRFClient(public_key)


@pytest.mark.parametrize(
    "server_key",
    [
        b"\x00" * 32,
        SCALAR_ORDER,
        b"\xff" * 32,
    ],
)
def test_invalid_server_key(server_key: bytes) -> None:
    with pytest.raises(OPRFProtocolError):
        make_server(server_key)


@pytest.mark.parametrize(
    "scalar",
    [
        b"\x00" * 32,
        SCALAR_ORDER,
    ],
)
def test_malformed_client_state(scalar: bytes) -> None:
    client, _, blind_result, evaluation = make_round()
    client_state = (
        scalar + blind_result.client_state[32:]
    )

    with pytest.raises(OPRFProtocolError):
        client.finalize(
            input_data=INPUT_DATA,
            client_state=client_state,
            evaluation=evaluation,
        )


@pytest.mark.parametrize(
    "proof",
    [
        b"\x00" * 64,
        SCALAR_ORDER + b"\x01" + b"\x00" * 31,
        b"\x01" + b"\x00" * 31 + SCALAR_ORDER,
    ],
)
def test_malformed_proof(proof: bytes) -> None:
    client, _, blind_result, evaluation = make_round()

    with pytest.raises(
        OPRFProtocolError,
        match="Malformed RFC 9497 VOPRF proof",
    ):
        client.finalize(
            input_data=INPUT_DATA,
            client_state=blind_result.client_state,
            evaluation=VOPRFEvaluation(
                evaluation.evaluated_element,
                proof,
            ),
        )


def test_wrong_public_key() -> None:
    client, _, blind_result, evaluation = make_round()
    other_server = make_server(
        b"\x02" + b"\x00" * 31
    )
    other_client = VOPRFClient(other_server.public_key)

    with pytest.raises(
        OPRFProtocolError,
        match="proof verification failed",
    ):
        other_client.finalize(
            input_data=INPUT_DATA,
            client_state=blind_result.client_state,
            evaluation=evaluation,
        )


def test_other_server_evaluation() -> None:
    server = make_server()
    other_server = make_server(
        b"\x02" + b"\x00" * 31
    )
    client = VOPRFClient(server.public_key)
    blind_result = client.blind(INPUT_DATA)
    evaluation = other_server.evaluate(
        blind_result.blinded_element
    )

    with pytest.raises(
        OPRFProtocolError,
        match="proof verification failed",
    ):
        client.finalize(
            input_data=INPUT_DATA,
            client_state=blind_result.client_state,
            evaluation=evaluation,
        )


def test_malformed_evaluated_element() -> None:
    client, _, blind_result, evaluation = make_round()

    with pytest.raises(
        OPRFProtocolError,
        match=(
            "^RFC 9497 VOPRF client finalization "
            "failed\\.$"
        ),
    ):
        client.finalize(
            input_data=INPUT_DATA,
            client_state=blind_result.client_state,
            evaluation=VOPRFEvaluation(
                b"\x00" * 32,
                evaluation.proof,
            ),
        )


def test_modified_proof() -> None:
    client, _, blind_result, evaluation = make_round()
    proof = (
        bytes([evaluation.proof[0] ^ 1])
        + evaluation.proof[1:]
    )

    with pytest.raises(
        OPRFProtocolError,
        match=(
            "^RFC 9497 VOPRF proof verification "
            "failed\\.$"
        ),
    ):
        client.finalize(
            input_data=INPUT_DATA,
            client_state=blind_result.client_state,
            evaluation=VOPRFEvaluation(
                evaluation.evaluated_element,
                proof,
            ),
        )


def test_mismatched_evaluation_proof() -> None:
    server = make_server()
    client = VOPRFClient(server.public_key)
    first = client.blind(INPUT_DATA)
    second = client.blind(INPUT_DATA)
    evaluation = server.evaluate(
        first.blinded_element
    )
    other_evaluation = server.evaluate(
        second.blinded_element
    )

    with pytest.raises(
        OPRFProtocolError,
        match=(
            "^RFC 9497 VOPRF proof verification "
            "failed\\.$"
        ),
    ):
        client.finalize(
            input_data=INPUT_DATA,
            client_state=second.client_state,
            evaluation=VOPRFEvaluation(
                other_evaluation.evaluated_element,
                evaluation.proof,
            ),
        )


def test_rfc_9497_vector() -> None:
    server_key = bytes.fromhex(
        "e6f73f344b79b379f1a0dd37e07ff62e"
        "38d9f71345ce62ae3a9bc60b04ccd909"
    )
    public_key = bytes.fromhex(
        "c803e2cc6b05fc15064549b5920659ca"
        "4a77b2cca6f04f6b357009335476ad4e"
    )
    blind = bytes.fromhex(
        "64d37aed22a27f5191de1c1d69fadb899"
        "d8862b58eb4220029e036ec4c1f6706"
    )
    blinded_element = bytes.fromhex(
        "863f330cc1a1259ed5a5998a23acfd37"
        "fb4351a793a5b3c090b642ddc439b945"
    )
    evaluation = VOPRFEvaluation(
        evaluated_element=bytes.fromhex(
            "aa8fa048764d5623868679402ff6108d"
            "2521884fa138cd7f9c7669a9a014267e"
        ),
        proof=bytes.fromhex(
            "ddef93772692e535d1a53903db243673"
            "55cc2cc78de93b3be5a8ffcc6985dd06"
            "6d4346421d17bf5117a2a1ff0fcb2a75"
            "9f58a539dfbe857a40bce4cf49ec600d"
        ),
    )
    expected = bytes.fromhex(
        "b58cfbe118e0cb94d79b5fd6a6dafb98"
        "764dff49c14e1770b566e42402da1a7d"
        "a4d8527693914139caee5bd03903af43"
        "a491351d23b430948dd50cde10d32b3c"
    )
    server = make_server(server_key)
    client = VOPRFClient(public_key)

    assert server.public_key == public_key
    assert client.finalize(
        input_data=b"\x00",
        client_state=blind + blinded_element,
        evaluation=evaluation,
    ) == expected

    generated = server.evaluate(blinded_element)
    assert (
        generated.evaluated_element
        == evaluation.evaluated_element
    )
    assert client.finalize(
        input_data=b"\x00",
        client_state=blind + blinded_element,
        evaluation=generated,
    ) == expected


def test_input_limit() -> None:
    server = make_server()
    client = VOPRFClient(server.public_key)
    input_data = b"a" * 65_534
    blind_result = client.blind(input_data)
    evaluation = server.evaluate(
        blind_result.blinded_element
    )

    assert len(
        client.finalize(
            input_data=input_data,
            client_state=blind_result.client_state,
            evaluation=evaluation,
        )
    ) == 64

    with pytest.raises(ValueError):
        client.blind(input_data + b"a")


@pytest.mark.parametrize("input_data", [b"", bytearray(b"x")])
def test_invalid_input(input_data: object) -> None:
    server = make_server()
    client = VOPRFClient(server.public_key)

    with pytest.raises((TypeError, ValueError)):
        client.blind(input_data)


@settings(max_examples=25, deadline=None)
@given(input_data=INPUTS, server_key=KEYS)
def test_round_trip_property(
    input_data: bytes,
    server_key: bytes,
) -> None:
    server = make_server(server_key)
    client = VOPRFClient(server.public_key)
    first = client.blind(input_data)
    first_evaluation = server.evaluate(
        first.blinded_element
    )
    first_output = client.finalize(
        input_data=input_data,
        client_state=first.client_state,
        evaluation=first_evaluation,
    )
    second = client.blind(input_data)
    second_evaluation = server.evaluate(
        second.blinded_element
    )
    second_output = client.finalize(
        input_data=input_data,
        client_state=second.client_state,
        evaluation=second_evaluation,
    )

    assert first.blinded_element != second.blinded_element
    assert first_evaluation.proof != second_evaluation.proof
    assert first_output == second_output


@settings(max_examples=25, deadline=None)
@given(inputs=INPUT_PAIRS)
def test_input_changes_output(
    inputs: tuple[bytes, bytes],
) -> None:
    server = make_server()
    client = VOPRFClient(server.public_key)
    outputs = []

    for input_data in inputs:
        blind_result = client.blind(input_data)
        evaluation = server.evaluate(
            blind_result.blinded_element
        )
        outputs.append(
            client.finalize(
                input_data=input_data,
                client_state=blind_result.client_state,
                evaluation=evaluation,
            )
        )

    assert outputs[0] != outputs[1]


@settings(max_examples=25, deadline=None)
@given(server_keys=KEY_PAIRS)
def test_key_changes_output(
    server_keys: tuple[bytes, bytes],
) -> None:
    outputs = []

    for server_key in server_keys:
        server = make_server(server_key)
        client = VOPRFClient(server.public_key)
        blind_result = client.blind(INPUT_DATA)
        evaluation = server.evaluate(
            blind_result.blinded_element
        )
        outputs.append(
            client.finalize(
                input_data=INPUT_DATA,
                client_state=blind_result.client_state,
                evaluation=evaluation,
            )
        )

    assert outputs[0] != outputs[1]


@settings(max_examples=25, deadline=None)
@given(
    element=INVALID_ELEMENTS,
    wide_value=INVALID_WIDE_VALUES,
)
def test_invalid_lengths_property(
    element: bytes,
    wide_value: bytes,
) -> None:
    backend = FakeBackend()
    client = VOPRFClient(b"p" * 32, backend)
    server = VOPRFServer("unused", backend)
    evaluation = VOPRFEvaluation(
        b"e" * 32,
        b"r" * 64,
    )

    with pytest.raises(ValueError):
        server.evaluate(element)
    with pytest.raises(ValueError):
        VOPRFClient(element, backend)
    with pytest.raises(ValueError):
        client.finalize(
            input_data=INPUT_DATA,
            client_state=wide_value,
            evaluation=evaluation,
        )
    with pytest.raises(ValueError):
        client.finalize(
            input_data=INPUT_DATA,
            client_state=b"s" * 64,
            evaluation=VOPRFEvaluation(
                element,
                b"r" * 64,
            ),
        )
    with pytest.raises(ValueError):
        client.finalize(
            input_data=INPUT_DATA,
            client_state=b"s" * 64,
            evaluation=VOPRFEvaluation(
                b"e" * 32,
                wide_value,
            ),
        )


@settings(max_examples=25, deadline=None)
@given(
    evaluated_element=st.binary(
        min_size=32,
        max_size=32,
    ),
    proof=st.binary(
        min_size=64,
        max_size=64,
    ),
)
def test_checked_values_property(
    evaluated_element: bytes,
    proof: bytes,
) -> None:
    client, _, blind_result, _ = make_round()

    try:
        output = client.finalize(
            input_data=INPUT_DATA,
            client_state=blind_result.client_state,
            evaluation=VOPRFEvaluation(
                evaluated_element,
                proof,
            ),
        )
    except OPRFProtocolError:
        return

    assert len(output) == 64


@settings(max_examples=25, deadline=None)
@given(
    blinded_element=st.binary(
        min_size=32,
        max_size=32,
    )
)
def test_checked_blinded_element(
    blinded_element: bytes,
) -> None:
    server = make_server()

    try:
        evaluation = server.evaluate(
            blinded_element
        )
    except OPRFProtocolError:
        return

    assert len(evaluation.evaluated_element) == 32
    assert len(evaluation.proof) == 64
