from __future__ import annotations

import base64
import binascii
import re


_BASE64URL = re.compile(r"[A-Za-z0-9_-]+")


def encode_unpadded(
    value: bytes,
    *,
    expected_length: int,
) -> str:
    """Encode an exact-length protocol value as canonical base64url."""
    _validate_expected_length(expected_length)
    if type(value) is not bytes or len(value) != expected_length:
        raise ValueError("protocol value has an invalid length")
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def decode_unpadded(
    value: str,
    *,
    expected_length: int,
) -> bytes:
    """Decode canonical, unpadded base64url of one exact byte length."""
    _validate_expected_length(expected_length)
    encoded_length = len(
        base64.urlsafe_b64encode(b"\x00" * expected_length).rstrip(b"=")
    )
    if (
        type(value) is not str
        or len(value) != encoded_length
        or _BASE64URL.fullmatch(value) is None
    ):
        raise ValueError("protocol value must be canonical base64url")
    try:
        decoded = base64.b64decode(
            value + "=" * (-len(value) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (binascii.Error, ValueError):
        raise ValueError(
            "protocol value must be canonical base64url"
        ) from None
    if len(decoded) != expected_length:
        raise ValueError("protocol value has an invalid length")
    if encode_unpadded(
        decoded,
        expected_length=expected_length,
    ) != value:
        raise ValueError("protocol value must be canonical base64url")
    return decoded


def _validate_expected_length(expected_length: object) -> None:
    if type(expected_length) is not int or expected_length < 1:
        raise ValueError("expected_length must be a positive integer")
