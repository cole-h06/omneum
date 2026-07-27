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
