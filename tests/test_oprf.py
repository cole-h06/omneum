from __future__ import annotations

import pytest

from verity.oprf import (
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
        server.evaluate(b"malformed")


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
        with pytest.raises(OPRFProtocolError):
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
        with pytest.raises(OPRFProtocolError):
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
        with pytest.raises(OPRFProtocolError):
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
