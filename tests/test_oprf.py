from __future__ import annotations

import pytest
from hypothesis import given, settings, strategies as st

from verity.oprf import (
    BlindResult,
    OPRFClient,
    OPRFProtocolError,
    OPRFServer,
)


INPUT_DATA = b"test input"
# Scalar 1 encoded as a fixed test key. Never use in production.
SERVER_KEY = b"\x01" + b"\x00" * 31
SCALAR_ORDER = bytes.fromhex(
    "edd3f55c1a631258d69cf7a2def9de14"
    "00000000000000000000000000000010"
)
SCALAR_ORDER_VALUE = int.from_bytes(SCALAR_ORDER, "little")
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
INVALID_ENCODINGS = st.one_of(
    st.binary(max_size=31),
    st.binary(min_size=33, max_size=64),
)


class FakeBackend:
    def __init__(
        self,
        *,
        blind_result: BlindResult | None = None,
        evaluated_element: bytes = b"e" * 32,
        output: bytes = b"o" * 64,
    ) -> None:
        self.blind_result = blind_result or BlindResult(
            blinded_element=b"b" * 32,
            client_state=b"s" * 32,
        )
        self.evaluated_element = evaluated_element
        self.output = output

    def blind(self, input_data: bytes) -> BlindResult:
        return self.blind_result

    def evaluate(
        self,
        server_key: bytes,
        blinded_element: bytes,
    ) -> bytes:
        return self.evaluated_element

    def finalize(
        self,
        input_data: bytes,
        client_state: bytes,
        evaluated_element: bytes,
    ) -> bytes:
        return self.output


def test_round_trip() -> None:
    client = OPRFClient()
    server = OPRFServer(SERVER_KEY)
    blind_result = client.blind(INPUT_DATA)
    evaluated_element = server.evaluate(
        blind_result.blinded_element
    )
    output = client.finalize(
        input_data=INPUT_DATA,
        client_state=blind_result.client_state,
        evaluated_element=evaluated_element,
    )

    assert isinstance(blind_result.blinded_element, bytes)
    assert len(blind_result.blinded_element) == 32
    assert isinstance(blind_result.client_state, bytes)
    assert len(blind_result.client_state) == 32
    assert isinstance(evaluated_element, bytes)
    assert len(evaluated_element) == 32
    assert isinstance(output, bytes)
    assert len(output) == 64


def test_repeated_input() -> None:
    client = OPRFClient()
    server = OPRFServer(SERVER_KEY)

    first_blind = client.blind(INPUT_DATA)
    first_evaluation = server.evaluate(
        first_blind.blinded_element
    )
    first_output = client.finalize(
        input_data=INPUT_DATA,
        client_state=first_blind.client_state,
        evaluated_element=first_evaluation,
    )

    second_blind = client.blind(INPUT_DATA)
    second_evaluation = server.evaluate(
        second_blind.blinded_element
    )
    second_output = client.finalize(
        input_data=INPUT_DATA,
        client_state=second_blind.client_state,
        evaluated_element=second_evaluation,
    )

    assert isinstance(first_blind.blinded_element, bytes)
    assert len(first_blind.blinded_element) == 32
    assert isinstance(first_blind.client_state, bytes)
    assert len(first_blind.client_state) == 32
    assert isinstance(first_evaluation, bytes)
    assert len(first_evaluation) == 32
    assert isinstance(first_output, bytes)
    assert len(first_output) == 64

    assert isinstance(second_blind.blinded_element, bytes)
    assert len(second_blind.blinded_element) == 32
    assert isinstance(second_blind.client_state, bytes)
    assert len(second_blind.client_state) == 32
    assert isinstance(second_evaluation, bytes)
    assert len(second_evaluation) == 32
    assert isinstance(second_output, bytes)
    assert len(second_output) == 64

    assert first_blind.blinded_element != second_blind.blinded_element
    assert first_output == second_output


def test_invalid_blinded_element() -> None:
    server = OPRFServer(SERVER_KEY)

    with pytest.raises(OPRFProtocolError):
        server.evaluate(b"\x00" * 32)


def test_blind_result_repr() -> None:
    result = BlindResult(
        blinded_element=b"visible blinded element",
        client_state=b"private client state",
    )

    assert b"private client state".decode() not in repr(result)
    assert b"private client state".decode() not in str(result)
    assert "visible blinded element" in repr(result)
    assert "visible blinded element" in str(result)


def test_custom_backend() -> None:
    backend = FakeBackend()
    client = OPRFClient(backend)
    server = OPRFServer(SERVER_KEY, backend)
    blind_result = client.blind(INPUT_DATA)
    evaluated_element = server.evaluate(
        blind_result.blinded_element
    )
    output = client.finalize(
        input_data=INPUT_DATA,
        client_state=blind_result.client_state,
        evaluated_element=evaluated_element,
    )

    assert len(blind_result.blinded_element) == 32
    assert len(blind_result.client_state) == 32
    assert len(evaluated_element) == 32
    assert len(output) == 64


@pytest.mark.parametrize("length", [31, 33])
@pytest.mark.parametrize(
    "name",
    ["blinded_element", "client_state"],
)
def test_invalid_blind_result(
    length: int,
    name: str,
) -> None:
    values = {
        "blinded_element": b"b" * 32,
        "client_state": b"s" * 32,
    }
    values[name] = b"x" * length
    backend = FakeBackend(
        blind_result=BlindResult(**values),
    )

    with pytest.raises(OPRFProtocolError):
        OPRFClient(backend).blind(INPUT_DATA)


@pytest.mark.parametrize("length", [31, 33])
def test_invalid_blinded_element_length(length: int) -> None:
    server = OPRFServer(SERVER_KEY, FakeBackend())

    with pytest.raises(ValueError):
        server.evaluate(b"x" * length)


@pytest.mark.parametrize("length", [31, 33])
def test_invalid_evaluation_result(length: int) -> None:
    server = OPRFServer(
        SERVER_KEY,
        FakeBackend(evaluated_element=b"x" * length),
    )

    with pytest.raises(OPRFProtocolError):
        server.evaluate(b"b" * 32)


@pytest.mark.parametrize("length", [31, 33])
@pytest.mark.parametrize(
    "name",
    ["client_state", "evaluated_element"],
)
def test_invalid_finalize_value(
    length: int,
    name: str,
) -> None:
    values = {
        "client_state": b"s" * 32,
        "evaluated_element": b"e" * 32,
    }
    values[name] = b"x" * length

    with pytest.raises(ValueError):
        OPRFClient(FakeBackend()).finalize(
            input_data=INPUT_DATA,
            **values,
        )


@pytest.mark.parametrize("length", [63, 65])
def test_invalid_finalize_result(length: int) -> None:
    client = OPRFClient(
        FakeBackend(output=b"x" * length),
    )

    with pytest.raises(OPRFProtocolError):
        client.finalize(
            input_data=INPUT_DATA,
            client_state=b"s" * 32,
            evaluated_element=b"e" * 32,
        )


def test_rfc_vector() -> None:
    # RFC 9497 Appendix A.1.1, test vector 1.
    input_data = bytes.fromhex("00")
    server_key = bytes.fromhex(
        "5ebcea5ee37023ccb9fc2d2019f9d773"
        "7be85591ae8652ffa9ef0f4d37063b0e"
    )
    client_state = bytes.fromhex(
        "64d37aed22a27f5191de1c1d69fadb89"
        "9d8862b58eb4220029e036ec4c1f6706"
    )
    blinded_element = bytes.fromhex(
        "609a0ae68c15a3cf6903766461307e5c"
        "8bb2f95e7e6550e1ffa2dc99e412803c"
    )
    expected_evaluation = bytes.fromhex(
        "7ec6578ae5120958eb2db1745758ff37"
        "9e77cb64fe77b0b2d8cc917ea0869c7e"
    )
    expected_output = bytes.fromhex(
        "527759c3d9366f277d8c6020418d96bb"
        "393ba2afb20ff90df23fb7708264e2f3"
        "ab9135e3bd69955851de4b1f9fe8a097"
        "3396719b7912ba9ee8aa7d0b5e24bcf6"
    )
    client = OPRFClient()
    server = OPRFServer(server_key)

    evaluated_element = server.evaluate(blinded_element)
    output = client.finalize(
        input_data=input_data,
        client_state=client_state,
        evaluated_element=evaluated_element,
    )

    assert evaluated_element == expected_evaluation
    assert output == expected_output


def test_invalid_server_key() -> None:
    client = OPRFClient()
    blinded_element = client.blind(INPUT_DATA).blinded_element
    invalid_keys = (
        SERVER_KEY[:31],
        b"\xff" * 33,
        SERVER_KEY + b"\x00",
        b"\x00" * 32,
        SCALAR_ORDER,
    )

    for server_key in invalid_keys:
        server = OPRFServer(server_key)

        with pytest.raises(OPRFProtocolError):
            server.evaluate(blinded_element)


def test_invalid_blinded_encodings() -> None:
    client = OPRFClient()
    server = OPRFServer(SERVER_KEY)
    blinded_element = client.blind(INPUT_DATA).blinded_element
    invalid_elements = (
        blinded_element[:31],
        b"\xff" * 33,
        blinded_element + b"\x00",
        b"\x00" * 32,
    )

    for element in invalid_elements:
        error = ValueError if len(element) != 32 else OPRFProtocolError

        with pytest.raises(error):
            server.evaluate(element)


def test_invalid_client_state() -> None:
    client = OPRFClient()
    server = OPRFServer(SERVER_KEY)
    blind_result = client.blind(INPUT_DATA)
    evaluated_element = server.evaluate(
        blind_result.blinded_element
    )
    invalid_states = (
        blind_result.client_state[:31],
        b"\xff" * 33,
        blind_result.client_state + b"\x00",
        b"\x00" * 32,
        SCALAR_ORDER,
    )

    for client_state in invalid_states:
        error = (
            ValueError
            if len(client_state) != 32
            else OPRFProtocolError
        )

        with pytest.raises(error):
            client.finalize(
                input_data=INPUT_DATA,
                client_state=client_state,
                evaluated_element=evaluated_element,
            )


def test_invalid_evaluated_encodings() -> None:
    client = OPRFClient()
    server = OPRFServer(SERVER_KEY)
    blind_result = client.blind(INPUT_DATA)
    evaluated_element = server.evaluate(
        blind_result.blinded_element
    )
    invalid_elements = (
        evaluated_element[:31],
        b"\xff" * 33,
        evaluated_element + b"\x00",
        b"\x00" * 32,
    )

    for element in invalid_elements:
        error = ValueError if len(element) != 32 else OPRFProtocolError

        with pytest.raises(error):
            client.finalize(
                input_data=INPUT_DATA,
                client_state=blind_result.client_state,
                evaluated_element=element,
            )


def test_input_limit() -> None:
    client = OPRFClient()
    server = OPRFServer(SERVER_KEY)
    input_data = b"a" * 65_534
    blind_result = client.blind(input_data)
    evaluated_element = server.evaluate(
        blind_result.blinded_element
    )

    output = client.finalize(
        input_data=input_data,
        client_state=blind_result.client_state,
        evaluated_element=evaluated_element,
    )

    assert len(output) == 64


def test_input_too_long() -> None:
    client = OPRFClient()
    input_data = b"a" * 65_535

    with pytest.raises(ValueError):
        client.blind(input_data)

    blind_result = client.blind(INPUT_DATA)

    with pytest.raises(ValueError):
        client.finalize(
            input_data=input_data,
            client_state=blind_result.client_state,
            evaluated_element=b"\x01" * 32,
        )


@settings(max_examples=25)
@given(input_data=INPUTS, server_key=KEYS)
def test_round_trip_property(
    input_data: bytes,
    server_key: bytes,
) -> None:
    client = OPRFClient()
    server = OPRFServer(server_key)
    first_blind = client.blind(input_data)
    first_evaluation = server.evaluate(
        first_blind.blinded_element
    )
    first_output = client.finalize(
        input_data=input_data,
        client_state=first_blind.client_state,
        evaluated_element=first_evaluation,
    )
    second_blind = client.blind(input_data)
    second_evaluation = server.evaluate(
        second_blind.blinded_element
    )
    second_output = client.finalize(
        input_data=input_data,
        client_state=second_blind.client_state,
        evaluated_element=second_evaluation,
    )

    assert len(first_output) == 64
    assert len(second_output) == 64
    assert first_output == second_output
    assert first_blind.blinded_element != second_blind.blinded_element


@settings(max_examples=25)
@given(
    inputs=INPUT_PAIRS,
    server_key=KEYS,
)
def test_input_changes_output(
    inputs: tuple[bytes, bytes],
    server_key: bytes,
) -> None:
    client = OPRFClient()
    server = OPRFServer(server_key)
    first_input, second_input = inputs
    first_blind = client.blind(first_input)
    first_evaluation = server.evaluate(
        first_blind.blinded_element
    )
    first_output = client.finalize(
        input_data=first_input,
        client_state=first_blind.client_state,
        evaluated_element=first_evaluation,
    )
    second_blind = client.blind(second_input)
    second_evaluation = server.evaluate(
        second_blind.blinded_element
    )
    second_output = client.finalize(
        input_data=second_input,
        client_state=second_blind.client_state,
        evaluated_element=second_evaluation,
    )

    assert first_output != second_output


@settings(max_examples=25)
@given(
    server_keys=KEY_PAIRS,
    input_data=INPUTS,
)
def test_key_changes_output(
    server_keys: tuple[bytes, bytes],
    input_data: bytes,
) -> None:
    client = OPRFClient()
    first_server = OPRFServer(server_keys[0])
    second_server = OPRFServer(server_keys[1])
    first_blind = client.blind(input_data)
    first_evaluation = first_server.evaluate(
        first_blind.blinded_element
    )
    first_output = client.finalize(
        input_data=input_data,
        client_state=first_blind.client_state,
        evaluated_element=first_evaluation,
    )
    second_blind = client.blind(input_data)
    second_evaluation = second_server.evaluate(
        second_blind.blinded_element
    )
    second_output = client.finalize(
        input_data=input_data,
        client_state=second_blind.client_state,
        evaluated_element=second_evaluation,
    )

    assert first_output != second_output


@settings(max_examples=50)
@given(value=INVALID_ENCODINGS)
def test_invalid_lengths(value: bytes) -> None:
    client = OPRFClient()
    server = OPRFServer(SERVER_KEY)
    blind_result = client.blind(INPUT_DATA)
    evaluated_element = server.evaluate(
        blind_result.blinded_element
    )
    if value:
        invalid_server = OPRFServer(value)

        with pytest.raises(OPRFProtocolError):
            invalid_server.evaluate(
                blind_result.blinded_element
            )
    else:
        with pytest.raises(ValueError):
            OPRFServer(value)

    with pytest.raises(ValueError):
        server.evaluate(value)

    with pytest.raises(ValueError):
        client.finalize(
            input_data=INPUT_DATA,
            client_state=value,
            evaluated_element=evaluated_element,
        )

    with pytest.raises(ValueError):
        client.finalize(
            input_data=INPUT_DATA,
            client_state=blind_result.client_state,
            evaluated_element=value,
        )


@settings(max_examples=100)
@given(element=st.binary(min_size=32, max_size=32))
def test_blinded_element_deserialization(element: bytes) -> None:
    server = OPRFServer(SERVER_KEY)

    try:
        evaluated_element = server.evaluate(element)
    except OPRFProtocolError:
        return

    assert isinstance(evaluated_element, bytes)
    assert len(evaluated_element) == 32


@settings(max_examples=100)
@given(element=st.binary(min_size=32, max_size=32))
def test_evaluated_element_deserialization(element: bytes) -> None:
    client = OPRFClient()
    blind_result = client.blind(INPUT_DATA)

    try:
        output = client.finalize(
            input_data=INPUT_DATA,
            client_state=blind_result.client_state,
            evaluated_element=element,
        )
    except OPRFProtocolError:
        return

    assert isinstance(output, bytes)
    assert len(output) == 64
