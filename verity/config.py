from __future__ import annotations

import hashlib
import os
import secrets
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from .base64url import decode_unpadded
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
DEFAULT_MAX_CONCURRENCY = 1
MIN_MAX_CONCURRENCY = 1
MAX_MAX_CONCURRENCY = 64
DEFAULT_EVALUATION_TIMEOUT_MS = 1_000
MIN_EVALUATION_TIMEOUT_MS = 1
MAX_EVALUATION_TIMEOUT_MS = 60_000
DEFAULT_ASSERTION_EVALUATION_MAX_CONCURRENCY = 1
MIN_ASSERTION_EVALUATION_MAX_CONCURRENCY = 1
MAX_ASSERTION_EVALUATION_MAX_CONCURRENCY = 64
DEFAULT_ASSERTION_EVALUATION_TIMEOUT_MS = 1_000
MIN_ASSERTION_EVALUATION_TIMEOUT_MS = 1
MAX_ASSERTION_EVALUATION_TIMEOUT_MS = 60_000

_DEPLOYMENT_ID = "VERITY_DEPLOYMENT_ID"
_KEY_VERSION = "VERITY_VOPRF_KEY_VERSION"
_PUBLIC_KEY = "VERITY_VOPRF_PUBLIC_KEY"
_PRIVATE_KEY_FILE = "VERITY_VOPRF_PRIVATE_KEY_FILE"
_MAX_CONCURRENCY = "VERITY_VOPRF_MAX_CONCURRENCY"
_EVALUATION_TIMEOUT_MS = "VERITY_VOPRF_EVALUATION_TIMEOUT_MS"
_ASSERTION_EVALUATION_MAX_CONCURRENCY = "VERITY_ASSERTION_EVALUATION_MAX_CONCURRENCY"
_ASSERTION_EVALUATION_TIMEOUT_MS = "VERITY_ASSERTION_EVALUATION_TIMEOUT_MS"
_FINGERPRINT_LABEL = b"VERITY-VOPRF-CONFIG\x00"


class ConfigurationError(ValueError):
    """Raised when deployment provisioning is invalid."""


@dataclass(frozen=True, slots=True)
class DeploymentConfig:
    deployment_id: str
    voprf_key_version: int
    voprf_public_key: bytes = field(repr=False)
    voprf_private_key_file: Path = field(repr=False)
    voprf_max_concurrency: int = DEFAULT_MAX_CONCURRENCY
    voprf_evaluation_timeout_ms: int = (
        DEFAULT_EVALUATION_TIMEOUT_MS
    )
    assertion_evaluation_max_concurrency: int = (
        DEFAULT_ASSERTION_EVALUATION_MAX_CONCURRENCY
    )
    assertion_evaluation_timeout_ms: int = DEFAULT_ASSERTION_EVALUATION_TIMEOUT_MS

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
        _validate_bounded_integer(
            self.voprf_max_concurrency,
            name="VOPRF maximum concurrency",
            minimum=MIN_MAX_CONCURRENCY,
            maximum=MAX_MAX_CONCURRENCY,
        )
        _validate_bounded_integer(
            self.voprf_evaluation_timeout_ms,
            name="VOPRF evaluation timeout",
            minimum=MIN_EVALUATION_TIMEOUT_MS,
            maximum=MAX_EVALUATION_TIMEOUT_MS,
        )
        _validate_bounded_integer(
            self.assertion_evaluation_max_concurrency,
            name="Inference maximum concurrency",
            minimum=MIN_ASSERTION_EVALUATION_MAX_CONCURRENCY,
            maximum=MAX_ASSERTION_EVALUATION_MAX_CONCURRENCY,
        )
        _validate_bounded_integer(
            self.assertion_evaluation_timeout_ms,
            name="Inference timeout",
            minimum=MIN_ASSERTION_EVALUATION_TIMEOUT_MS,
            maximum=MAX_ASSERTION_EVALUATION_TIMEOUT_MS,
        )


@dataclass(frozen=True, slots=True)
class DeploymentState:
    deployment_id: str
    voprf_key_version: int
    configuration_fingerprint: str
    voprf_server: VOPRFServer = field(repr=False)
    voprf_max_concurrency: int = DEFAULT_MAX_CONCURRENCY
    voprf_evaluation_timeout_ms: int = (
        DEFAULT_EVALUATION_TIMEOUT_MS
    )
    assertion_evaluation_max_concurrency: int = (
        DEFAULT_ASSERTION_EVALUATION_MAX_CONCURRENCY
    )
    assertion_evaluation_timeout_ms: int = DEFAULT_ASSERTION_EVALUATION_TIMEOUT_MS


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
        voprf_max_concurrency=_optional_bounded_integer(
            values,
            name=_MAX_CONCURRENCY,
            default=DEFAULT_MAX_CONCURRENCY,
            minimum=MIN_MAX_CONCURRENCY,
            maximum=MAX_MAX_CONCURRENCY,
        ),
        voprf_evaluation_timeout_ms=_optional_bounded_integer(
            values,
            name=_EVALUATION_TIMEOUT_MS,
            default=DEFAULT_EVALUATION_TIMEOUT_MS,
            minimum=MIN_EVALUATION_TIMEOUT_MS,
            maximum=MAX_EVALUATION_TIMEOUT_MS,
        ),
        assertion_evaluation_max_concurrency=_optional_bounded_integer(
            values,
            name=_ASSERTION_EVALUATION_MAX_CONCURRENCY,
            default=DEFAULT_ASSERTION_EVALUATION_MAX_CONCURRENCY,
            minimum=MIN_ASSERTION_EVALUATION_MAX_CONCURRENCY,
            maximum=MAX_ASSERTION_EVALUATION_MAX_CONCURRENCY,
        ),
        assertion_evaluation_timeout_ms=_optional_bounded_integer(
            values,
            name=_ASSERTION_EVALUATION_TIMEOUT_MS,
            default=DEFAULT_ASSERTION_EVALUATION_TIMEOUT_MS,
            minimum=MIN_ASSERTION_EVALUATION_TIMEOUT_MS,
            maximum=MAX_ASSERTION_EVALUATION_TIMEOUT_MS,
        ),
    )
    try:
        VOPRFClient(config.voprf_public_key)
        server = VOPRFServer(
            config.voprf_private_key_file
        )
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
        voprf_max_concurrency=config.voprf_max_concurrency,
        voprf_evaluation_timeout_ms=(
            config.voprf_evaluation_timeout_ms
        ),
        assertion_evaluation_max_concurrency=(
            config.assertion_evaluation_max_concurrency
        ),
        assertion_evaluation_timeout_ms=config.assertion_evaluation_timeout_ms,
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


def _validate_bounded_integer(
    value: object,
    *,
    name: str,
    minimum: int,
    maximum: int,
) -> None:
    if type(value) is not int:
        raise ConfigurationError(
            f"{name} must be an integer."
        )
    if not minimum <= value <= maximum:
        raise ConfigurationError(
            f"{name} is out of range."
        )


def _optional_bounded_integer(
    environ: Mapping[str, str],
    *,
    name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    value = environ.get(name)
    if value is None:
        return default
    if (
        not value
        or not value.isascii()
        or not value.isdecimal()
        or (len(value) > 1 and value.startswith("0"))
    ):
        raise ConfigurationError(
            f"{name} must be a canonical integer."
        )
    parsed = int(value)
    _validate_bounded_integer(
        parsed,
        name=name,
        minimum=minimum,
        maximum=maximum,
    )
    return parsed


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
    try:
        return decode_unpadded(
            value,
            expected_length=32,
        )
    except ValueError:
        raise ConfigurationError(
            "VERITY_VOPRF_PUBLIC_KEY must be canonical base64url."
        ) from None


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
