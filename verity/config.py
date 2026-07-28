from __future__ import annotations

import base64
import binascii
import hashlib
import os
import re
import secrets
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from .linkage import ENCODING_VERSION
from .oprf import (
    CIPHERSUITE,
    OPRFError,
    VOPRFClient,
    VOPRFServer,
)


PROTOCOL_VERSION = "v1"
ALGORITHM_VERSION = "verity-v1"
VOPRF_MODE = "voprf"
MIN_KEY_VERSION = 1
MAX_KEY_VERSION = 2**32 - 1

_DEPLOYMENT_ID = "VERITY_DEPLOYMENT_ID"
_KEY_VERSION = "VERITY_VOPRF_KEY_VERSION"
_PUBLIC_KEY = "VERITY_VOPRF_PUBLIC_KEY"
_PRIVATE_KEY_FILE = "VERITY_VOPRF_PRIVATE_KEY_FILE"
_BASE64URL = re.compile(r"[A-Za-z0-9_-]+")
_FINGERPRINT_LABEL = b"VERITY-VOPRF-CONFIG\x00"


class ConfigurationError(ValueError):
    """Raised when deployment provisioning is invalid."""


@dataclass(frozen=True, slots=True)
class DeploymentConfig:
    deployment_id: str
    voprf_key_version: int
    voprf_public_key: bytes = field(repr=False)
    voprf_private_key_file: Path = field(repr=False)

    def __post_init__(self) -> None:
        _validate_deployment_id(self.deployment_id)
        _validate_key_version(self.voprf_key_version)
        if type(self.voprf_public_key) is not bytes:
            raise ConfigurationError(
                "VOPRF public key must be bytes."
            )
        if len(self.voprf_public_key) != 32:
            raise ConfigurationError(
                "VOPRF public key must be 32 bytes."
            )
        if not isinstance(
            self.voprf_private_key_file,
            Path,
        ):
            raise ConfigurationError(
                "VOPRF private key file must be a path."
            )


@dataclass(frozen=True, slots=True)
class DeploymentState:
    deployment_id: str
    voprf_key_version: int
    configuration_fingerprint: str
    voprf_server: VOPRFServer = field(repr=False)


def load_deployment_state(
    environ: Mapping[str, str] | None = None,
) -> DeploymentState:
    values = os.environ if environ is None else environ
    config = DeploymentConfig(
        deployment_id=_required(values, _DEPLOYMENT_ID),
        voprf_key_version=_parse_key_version(
            _required(values, _KEY_VERSION)
        ),
        voprf_public_key=_decode_public_key(
            _required(values, _PUBLIC_KEY)
        ),
        voprf_private_key_file=Path(
            _required(values, _PRIVATE_KEY_FILE)
        ),
    )
    private_key = _read_private_key(
        config.voprf_private_key_file
    )

    try:
        VOPRFClient(config.voprf_public_key)
        server = VOPRFServer(private_key)
    except OPRFError:
        raise ConfigurationError(
            "VOPRF key material is invalid."
        ) from None

    if not secrets.compare_digest(
        server.public_key,
        config.voprf_public_key,
    ):
        raise ConfigurationError(
            "Configured VOPRF keys do not match."
        )

    return DeploymentState(
        deployment_id=config.deployment_id,
        voprf_key_version=config.voprf_key_version,
        configuration_fingerprint=_fingerprint(config),
        voprf_server=server,
    )


def _required(
    environ: Mapping[str, str],
    name: str,
) -> str:
    value = environ.get(name)
    if value is None or not value:
        raise ConfigurationError(
            f"{name} is required."
        )
    return value


def _validate_deployment_id(deployment_id: object) -> None:
    if type(deployment_id) is not str:
        raise ConfigurationError(
            "Deployment ID must be a string."
        )

    prefix = "urn:uuid:"
    if not deployment_id.startswith(prefix):
        raise ConfigurationError(
            "Deployment ID must be a canonical UUID URN."
        )

    try:
        parsed = uuid.UUID(deployment_id[len(prefix):])
    except (ValueError, AttributeError):
        raise ConfigurationError(
            "Deployment ID must be a canonical UUID URN."
        ) from None

    if deployment_id != f"{prefix}{parsed}":
        raise ConfigurationError(
            "Deployment ID must be a canonical UUID URN."
        )


def _validate_key_version(version: object) -> None:
    if type(version) is not int:
        raise ConfigurationError(
            "VOPRF key version must be an integer."
        )
    if not MIN_KEY_VERSION <= version <= MAX_KEY_VERSION:
        raise ConfigurationError(
            "VOPRF key version is out of range."
        )


def _parse_key_version(value: str) -> int:
    if not value.isascii() or not value.isdecimal():
        raise ConfigurationError(
            "VERITY_VOPRF_KEY_VERSION must be an integer."
        )
    if len(value) > 1 and value.startswith("0"):
        raise ConfigurationError(
            "VERITY_VOPRF_KEY_VERSION must be canonical."
        )

    version = int(value)
    _validate_key_version(version)
    return version


def _decode_public_key(value: str) -> bytes:
    if _BASE64URL.fullmatch(value) is None:
        raise ConfigurationError(
            "VERITY_VOPRF_PUBLIC_KEY must be canonical base64url."
        )

    padding = "=" * (-len(value) % 4)
    try:
        decoded = base64.b64decode(
            value + padding,
            altchars=b"-_",
            validate=True,
        )
    except (binascii.Error, ValueError):
        raise ConfigurationError(
            "VERITY_VOPRF_PUBLIC_KEY must be canonical base64url."
        ) from None

    canonical = base64.urlsafe_b64encode(
        decoded
    ).rstrip(b"=").decode("ascii")
    if canonical != value:
        raise ConfigurationError(
            "VERITY_VOPRF_PUBLIC_KEY must be canonical base64url."
        )
    if len(decoded) != 32:
        raise ConfigurationError(
            "VOPRF public key must be 32 bytes."
        )
    return decoded


def _read_private_key(path: Path) -> bytes:
    try:
        if not path.is_file():
            raise OSError
        with path.open("rb") as secret_file:
            private_key = secret_file.read(33)
    except OSError:
        raise ConfigurationError(
            "Unable to read VOPRF private key file."
        ) from None

    if len(private_key) != 32:
        raise ConfigurationError(
            "VOPRF private key file must contain 32 bytes."
        )
    return private_key


def _fingerprint(config: DeploymentConfig) -> str:
    # This diagnostic value does not authenticate the configured public key.
    fields = (
        config.deployment_id.encode("ascii"),
        config.voprf_key_version.to_bytes(4, "big"),
        VOPRF_MODE.encode("ascii"),
        CIPHERSUITE.encode("ascii"),
        ENCODING_VERSION.to_bytes(2, "big"),
        config.voprf_public_key,
    )
    encoded = bytearray(_FINGERPRINT_LABEL)
    # Each field is its two-byte big-endian length followed by its exact bytes.
    for value in fields:
        encoded.extend(len(value).to_bytes(2, "big"))
        encoded.extend(value)
    return hashlib.sha256(encoded).hexdigest()
