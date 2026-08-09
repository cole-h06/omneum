from __future__ import annotations

import base64
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import verity.config as config_module
from verity.config import (
    DEFAULT_EVALUATION_TIMEOUT_MS,
    DEFAULT_ASSERTION_EVALUATION_MAX_CONCURRENCY,
    DEFAULT_ASSERTION_EVALUATION_TIMEOUT_MS,
    DEFAULT_MAX_CONCURRENCY,
    MAX_EVALUATION_TIMEOUT_MS,
    MAX_ASSERTION_EVALUATION_MAX_CONCURRENCY,
    MAX_ASSERTION_EVALUATION_TIMEOUT_MS,
    MAX_KEY_VERSION,
    MAX_MAX_CONCURRENCY,
    MIN_EVALUATION_TIMEOUT_MS,
    MIN_ASSERTION_EVALUATION_MAX_CONCURRENCY,
    MIN_ASSERTION_EVALUATION_TIMEOUT_MS,
    MIN_MAX_CONCURRENCY,
    ConfigurationError,
    DeploymentConfig,
    load_deployment_state,
)
from verity.oprf import VOPRFServer
from verity.transport.mcp import create_server


DEPLOYMENT_ID = (
    "urn:uuid:8d96fc18-f40f-4ec7-8ae8-f3711d88b741"
)
# Scalar 1 encoded as a fixed test key. Never use in production.
PRIVATE_KEY = b"\x01" + b"\x00" * 31


def encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(
        value
    ).rstrip(b"=").decode("ascii")


def provisioning(
    private_key_file: Path,
    *,
    private_key: bytes = PRIVATE_KEY,
    public_key: bytes | None = None,
) -> dict[str, str]:
    private_key_file.write_bytes(private_key)
    if public_key is None:
        public_key = VOPRFServer(
            private_key_file
        ).public_key
    return {
        "VERITY_DEPLOYMENT_ID": DEPLOYMENT_ID,
        "VERITY_VOPRF_KEY_VERSION": "1",
        "VERITY_VOPRF_PUBLIC_KEY": encode(public_key),
        "VERITY_VOPRF_PRIVATE_KEY_FILE": str(
            private_key_file
        ),
    }


def test_load_config(tmp_path: Path) -> None:
    environ = provisioning(
        tmp_path / "voprf.key"
    )
    state = load_deployment_state(environ)

    assert state.deployment_id == DEPLOYMENT_ID
    assert state.voprf_key_version == 1
    assert len(state.configuration_fingerprint) == 64
    assert (
        state.voprf_max_concurrency
        == DEFAULT_MAX_CONCURRENCY
    )
    assert (
        state.voprf_evaluation_timeout_ms
        == DEFAULT_EVALUATION_TIMEOUT_MS
    )
    assert (
        state.assertion_evaluation_max_concurrency
        == DEFAULT_ASSERTION_EVALUATION_MAX_CONCURRENCY
    )
    assert state.assertion_evaluation_timeout_ms == DEFAULT_ASSERTION_EVALUATION_TIMEOUT_MS
    assert (
        state.voprf_server.public_key
        == VOPRFServer(
            Path(
                environ[
                    "VERITY_VOPRF_PRIVATE_KEY_FILE"
                ]
            )
        ).public_key
    )


@pytest.mark.parametrize(
    ("name", "minimum", "maximum", "attribute"),
    [
        (
            "VERITY_VOPRF_MAX_CONCURRENCY",
            MIN_MAX_CONCURRENCY,
            MAX_MAX_CONCURRENCY,
            "voprf_max_concurrency",
        ),
        (
            "VERITY_VOPRF_EVALUATION_TIMEOUT_MS",
            MIN_EVALUATION_TIMEOUT_MS,
            MAX_EVALUATION_TIMEOUT_MS,
            "voprf_evaluation_timeout_ms",
        ),
        (
            "VERITY_ASSERTION_EVALUATION_MAX_CONCURRENCY",
            MIN_ASSERTION_EVALUATION_MAX_CONCURRENCY,
            MAX_ASSERTION_EVALUATION_MAX_CONCURRENCY,
            "assertion_evaluation_max_concurrency",
        ),
        (
            "VERITY_ASSERTION_EVALUATION_TIMEOUT_MS",
            MIN_ASSERTION_EVALUATION_TIMEOUT_MS,
            MAX_ASSERTION_EVALUATION_TIMEOUT_MS,
            "assertion_evaluation_timeout_ms",
        ),
    ],
)
def test_resource_control_boundaries(
    tmp_path: Path,
    name: str,
    minimum: int,
    maximum: int,
    attribute: str,
) -> None:
    for value in (minimum, maximum):
        environ = provisioning(
            tmp_path / f"{name}-{value}.key"
        )
        environ[name] = str(value)
        state = load_deployment_state(environ)
        assert getattr(state, attribute) == value


@pytest.mark.parametrize(
    ("name", "values"),
    [
        (
            "VERITY_VOPRF_MAX_CONCURRENCY",
            ("", "0", "65", "-1", "01", "1.0", "True"),
        ),
        (
            "VERITY_VOPRF_EVALUATION_TIMEOUT_MS",
            ("", "0", "60001", "-1", "01", "1.0", "True"),
        ),
        (
            "VERITY_ASSERTION_EVALUATION_MAX_CONCURRENCY",
            ("", "0", "65", "-1", "01", "1.0", "True"),
        ),
        (
            "VERITY_ASSERTION_EVALUATION_TIMEOUT_MS",
            ("", "0", "60001", "-1", "01", "1.0", "True"),
        ),
    ],
)
def test_invalid_resource_controls(
    tmp_path: Path,
    name: str,
    values: tuple[str, ...],
) -> None:
    for value in values:
        environ = provisioning(
            tmp_path / f"{name}-{len(value)}.key"
        )
        environ[name] = value
        with pytest.raises(ConfigurationError):
            load_deployment_state(environ)


def test_stable_server(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    servers = []
    server_type = config_module.VOPRFServer

    def create_voprf_server(
        private_key_file: Path,
    ) -> VOPRFServer:
        server = server_type(private_key_file)
        servers.append(server)
        return server

    monkeypatch.setattr(
        config_module,
        "VOPRFServer",
        create_voprf_server,
    )
    state = load_deployment_state(
        provisioning(tmp_path / "voprf.key")
    )
    create_server(state)
    create_server(state)

    assert servers == [state.voprf_server]


def test_fingerprint(tmp_path: Path) -> None:
    state = load_deployment_state(
        provisioning(tmp_path / "voprf.key")
    )

    assert state.configuration_fingerprint == (
        "5b8742c8a3338fd212f3be06635d185b"
        "f8804301b2ea12945ba1dd0e1969e82a"
    )


@pytest.mark.parametrize(
    "name",
    [
        "VERITY_DEPLOYMENT_ID",
        "VERITY_VOPRF_KEY_VERSION",
        "VERITY_VOPRF_PUBLIC_KEY",
        "VERITY_VOPRF_PRIVATE_KEY_FILE",
    ],
)
def test_missing_config(
    tmp_path: Path,
    name: str,
) -> None:
    environ = provisioning(
        tmp_path / "voprf.key"
    )
    del environ[name]

    with pytest.raises(
        ConfigurationError,
        match=f"^{name} is required\\.$",
    ):
        load_deployment_state(environ)


@pytest.mark.parametrize(
    "deployment_id",
    [
        "8d96fc18-f40f-4ec7-8ae8-f3711d88b741",
        "URN:UUID:8d96fc18-f40f-4ec7-8ae8-f3711d88b741",
        "urn:uuid:8D96FC18-F40F-4EC7-8AE8-F3711D88B741",
        "urn:uuid:{8d96fc18-f40f-4ec7-8ae8-f3711d88b741}",
        "urn:uuid:not-a-uuid",
    ],
)
def test_invalid_deployment_id(
    tmp_path: Path,
    deployment_id: str,
) -> None:
    environ = provisioning(
        tmp_path / "voprf.key"
    )
    environ["VERITY_DEPLOYMENT_ID"] = deployment_id

    with pytest.raises(ConfigurationError):
        load_deployment_state(environ)


@pytest.mark.parametrize(
    "version",
    [
        "0",
        "-1",
        "01",
        str(MAX_KEY_VERSION + 1),
        "1.0",
        "True",
        " 1",
        "1 ",
    ],
)
def test_invalid_key_version(
    tmp_path: Path,
    version: str,
) -> None:
    environ = provisioning(
        tmp_path / "voprf.key"
    )
    environ["VERITY_VOPRF_KEY_VERSION"] = version

    with pytest.raises(ConfigurationError):
        load_deployment_state(environ)


@pytest.mark.parametrize(
    "version",
    [
        1,
        MAX_KEY_VERSION,
    ],
)
def test_key_version_boundary(
    tmp_path: Path,
    version: int,
) -> None:
    environ = provisioning(
        tmp_path / f"{version}.key"
    )
    environ["VERITY_VOPRF_KEY_VERSION"] = str(
        version
    )

    assert (
        load_deployment_state(
            environ
        ).voprf_key_version
        == version
    )


def test_boolean_key_version(tmp_path: Path) -> None:
    config = provisioning(
        tmp_path / "voprf.key"
    )

    with pytest.raises(ConfigurationError):
        DeploymentConfig(
            deployment_id=DEPLOYMENT_ID,
            voprf_key_version=True,
            voprf_public_key=base64.urlsafe_b64decode(
                config["VERITY_VOPRF_PUBLIC_KEY"]
                + "="
            ),
            voprf_private_key_file=Path(
                config["VERITY_VOPRF_PRIVATE_KEY_FILE"]
            ),
        )


@pytest.mark.parametrize(
    "public_key",
    [
        "",
        "not+base64url",
        "a" * 42 + "=",
        " a" * 21 + "a",
    ],
)
def test_invalid_public_key_encoding(
    tmp_path: Path,
    public_key: str,
) -> None:
    environ = provisioning(
        tmp_path / "voprf.key"
    )
    environ["VERITY_VOPRF_PUBLIC_KEY"] = public_key

    with pytest.raises(ConfigurationError):
        load_deployment_state(environ)


def test_noncanonical_public_key(
    tmp_path: Path,
) -> None:
    environ = provisioning(
        tmp_path / "voprf.key"
    )
    public_key = environ["VERITY_VOPRF_PUBLIC_KEY"]
    alphabet = (
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "abcdefghijklmnopqrstuvwxyz"
        "0123456789-_"
    )
    index = alphabet.index(public_key[-1])
    environ["VERITY_VOPRF_PUBLIC_KEY"] = (
        public_key[:-1] + alphabet[index + 1]
    )

    with pytest.raises(ConfigurationError):
        load_deployment_state(environ)


@pytest.mark.parametrize(
    ("target", "key"),
    [
        pytest.param("public", b"x" * 31, id="public-short"),
        pytest.param("public", b"x" * 33, id="public-long"),
        pytest.param("public", b"\x00" * 32, id="public-zero"),
        pytest.param("public", b"\xff" * 32, id="public-maximum"),
        pytest.param("private", b"x" * 31, id="private-short"),
        pytest.param("private", b"x" * 33, id="private-long"),
        pytest.param("private", b"\x00" * 32, id="private-zero"),
        pytest.param("private", b"\xff" * 32, id="private-maximum"),
    ],
)
def test_invalid_key_material(
    tmp_path: Path,
    target: str,
    key: bytes,
) -> None:
    environ = provisioning(
        tmp_path / "voprf.key"
    )
    if target == "public":
        environ["VERITY_VOPRF_PUBLIC_KEY"] = encode(key)
    else:
        Path(
            environ["VERITY_VOPRF_PRIVATE_KEY_FILE"]
        ).write_bytes(key)

    with pytest.raises(ConfigurationError):
        load_deployment_state(environ)


def test_missing_private_key(tmp_path: Path) -> None:
    path = tmp_path / "missing.key"
    environ = provisioning(
        tmp_path / "voprf.key"
    )
    environ["VERITY_VOPRF_PRIVATE_KEY_FILE"] = str(
        path
    )

    with pytest.raises(ConfigurationError):
        load_deployment_state(environ)

    assert not path.exists()


def test_private_key_directory(tmp_path: Path) -> None:
    environ = provisioning(
        tmp_path / "voprf.key"
    )
    environ["VERITY_VOPRF_PRIVATE_KEY_FILE"] = str(
        tmp_path
    )

    with pytest.raises(ConfigurationError):
        load_deployment_state(environ)


def test_key_mismatch(tmp_path: Path) -> None:
    other_key_file = tmp_path / "other.key"
    other_key_file.write_bytes(
        b"\x02" + b"\x00" * 31
    )
    public_key = VOPRFServer(
        other_key_file
    ).public_key
    environ = provisioning(
        tmp_path / "voprf.key",
        public_key=public_key,
    )

    with pytest.raises(
        ConfigurationError,
        match="^Configured VOPRF keys do not match\\.$",
    ):
        load_deployment_state(environ)


def test_config_repr(tmp_path: Path) -> None:
    environ = provisioning(
        tmp_path / "private-value.key"
    )
    public_key = environ["VERITY_VOPRF_PUBLIC_KEY"]
    private_key_file = environ[
        "VERITY_VOPRF_PRIVATE_KEY_FILE"
    ]
    state = load_deployment_state(environ)
    config = DeploymentConfig(
        deployment_id=DEPLOYMENT_ID,
        voprf_key_version=1,
        voprf_public_key=state.voprf_server.public_key,
        voprf_private_key_file=Path(private_key_file),
    )

    for value in (
        public_key,
        private_key_file,
        PRIVATE_KEY.hex(),
    ):
        assert value not in repr(config)
        assert value not in repr(state)
        assert value not in str(config)
        assert value not in str(state)


def test_error_secrecy(tmp_path: Path) -> None:
    path = tmp_path / "private-value.key"
    public_key = "private-public-value"
    environ = {
        "VERITY_DEPLOYMENT_ID": DEPLOYMENT_ID,
        "VERITY_VOPRF_KEY_VERSION": "1",
        "VERITY_VOPRF_PUBLIC_KEY": public_key,
        "VERITY_VOPRF_PRIVATE_KEY_FILE": str(path),
    }

    with pytest.raises(ConfigurationError) as failure:
        load_deployment_state(environ)

    message = str(failure.value)
    assert str(path) not in message
    assert public_key not in message


def test_config_is_immutable(tmp_path: Path) -> None:
    state = load_deployment_state(
        provisioning(tmp_path / "voprf.key")
    )

    with pytest.raises(FrozenInstanceError):
        state.voprf_key_version = 2
