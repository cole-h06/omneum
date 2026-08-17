from dataclasses import dataclass
from pathlib import Path

from omneum.base64url import encode_unpadded
from omneum.oprf import ELEMENT_LENGTH
from omneum.paths import get_private_key_path
from omneum_oprf import provision_server_key


@dataclass(frozen=True, slots=True)
class VOPRFKeyMaterial:
    private_key_file: Path
    public_key: bytes


def generate_voprf_key_material() -> VOPRFKeyMaterial:
    path = get_private_key_path()

    public_key = provision_server_key(str(path))

    return VOPRFKeyMaterial(
        private_key_file=path,
        public_key=public_key,
    )


def encode_public_key(public_key: bytes) -> str:
    return encode_unpadded(
        public_key,
        expected_length=ELEMENT_LENGTH,
    )