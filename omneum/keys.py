"""Public-key encoding only. Private-key provisioning belongs to omneumd."""
from omneum.base64url import encode_unpadded
from omneum.oprf import ELEMENT_LENGTH


def encode_public_key(public_key: bytes) -> str:
    return encode_unpadded(public_key, expected_length=ELEMENT_LENGTH)
