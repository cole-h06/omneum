import pytest

from verity.base64url import decode_unpadded, encode_unpadded


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
        "",
        "A" * 42,
        "A" * 44,
        "A" * 42 + "=",
        "A" * 42 + "+",
    ],
)
def test_invalid_encoding(value: str) -> None:
    with pytest.raises(ValueError):
        decode_unpadded(
            value,
            expected_length=32,
        )


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
