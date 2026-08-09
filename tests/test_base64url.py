import pytest

from verity.base64url import decode_unpadded, encode_unpadded


CANONICAL = encode_unpadded(b"\x00" * 32, expected_length=32)


def test_round_trip() -> None:
    value = bytes(range(32))
    encoded = encode_unpadded(
        value,
        expected_length=32,
    )

    assert "=" not in encoded
    assert decode_unpadded(
        encoded,
        expected_length=32,
    ) == value


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("", id="empty"),
        pytest.param(CANONICAL[:-1], id="truncated"),
        pytest.param(CANONICAL + "A", id="extended"),
        pytest.param(CANONICAL + "=", id="padding"),
        pytest.param(CANONICAL[:-1] + "+", id="alphabet"),
        pytest.param(CANONICAL[:-1] + " ", id="whitespace"),
        pytest.param(CANONICAL[:-1] + "B", id="trailing-bits"),
    ],
)
def test_invalid_encoding(value: str) -> None:
    with pytest.raises(
        ValueError,
        match="^protocol value must be canonical base64url$",
    ) as caught:
        decode_unpadded(
            value,
            expected_length=32,
        )
    assert str(caught.value) == "protocol value must be canonical base64url"
    assert CANONICAL not in repr(caught.value)


def test_invalid_types() -> None:
    with pytest.raises(ValueError):
        encode_unpadded(
            bytearray(32),
            expected_length=32,
        )
    with pytest.raises(ValueError):
        decode_unpadded(
            b"A" * 43,
            expected_length=32,
        )
    with pytest.raises(ValueError):
        decode_unpadded(
            "A" * 43,
            expected_length=True,
        )
