import base64
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import omneum.config as config_module
from omneum.config import (
    DEFAULT_ASSERTION_EVALUATION_MAX_CONCURRENCY,
    DEFAULT_ASSERTION_EVALUATION_TIMEOUT_MS,
    DEFAULT_EVALUATION_TIMEOUT_MS,
    DEFAULT_MAX_CONCURRENCY,
    MAX_KEY_VERSION,
    ConfigurationError,
    DeploymentConfig,
    load_deployment_state,
)
from omneum.oprf import VOPRFServer
from omneum.transport.mcp import create_server


DEPLOYMENT_ID = "urn:uuid:8d96fc18-f40f-4ec7-8ae8-f3711d88b741"
PRIVATE_KEY = b"\x01" + b"\x00" * 31


def persisted_state(tmp_path, monkeypatch, **changes):
    config_dir = tmp_path / "config"
    key_path = config_dir / "keys" / "voprf.key"
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(PRIVATE_KEY)
    public_key = changes.pop("public_key", VOPRFServer(key_path).public_key)
    key_path.write_bytes(changes.pop("private_key", PRIVATE_KEY))
    encoded_public_key = changes.pop(
        "encoded_public_key",
        base64.urlsafe_b64encode(public_key).rstrip(b"=").decode("ascii"),
    )
    omitted = changes.pop("omitted", ())
    values = {
        "deployment_id": DEPLOYMENT_ID,
        "voprf_key_version": 1,
        "voprf_public_key": encoded_public_key,
    }
    values.update(changes)
    for name in omitted:
        del values[name]
    lines = []
    for name, value in values.items():
        if isinstance(value, str):
            lines.append(f'{name} = "{value}"')
        elif isinstance(value, bool):
            lines.append(f"{name} = {str(value).lower()}")
        else:
            lines.append(f"{name} = {value}")
    (config_dir / "config.toml").write_text("\n".join(lines) + "\n")
    monkeypatch.setattr(config_module, "get_config_dir", lambda: config_dir)
    monkeypatch.setattr(config_module, "get_private_key_path", lambda: key_path)
    return load_deployment_state()


def test_load_persisted_state(tmp_path, monkeypatch):
    state = persisted_state(tmp_path, monkeypatch)
    assert state.deployment_id == DEPLOYMENT_ID
    assert state.voprf_key_version == 1
    assert len(state.configuration_fingerprint) == 64
    assert state.voprf_max_concurrency == DEFAULT_MAX_CONCURRENCY
    assert state.voprf_evaluation_timeout_ms == DEFAULT_EVALUATION_TIMEOUT_MS
    assert state.assertion_evaluation_max_concurrency == DEFAULT_ASSERTION_EVALUATION_MAX_CONCURRENCY
    assert state.assertion_evaluation_timeout_ms == DEFAULT_ASSERTION_EVALUATION_TIMEOUT_MS


def test_stable_server(tmp_path, monkeypatch):
    servers = []
    server_type = config_module.VOPRFServer

    def create_voprf_server(path):
        server = server_type(path)
        servers.append(server)
        return server

    monkeypatch.setattr(config_module, "VOPRFServer", create_voprf_server)
    state = persisted_state(tmp_path, monkeypatch)
    create_server(state)
    create_server(state)
    assert servers == [state.voprf_server]


def test_fingerprint(tmp_path, monkeypatch):
    assert persisted_state(tmp_path, monkeypatch).configuration_fingerprint == (
        "81070db4aa6e52c44b435e6a0d7bcda1"
        "09ac0f1910992670b4821cca6bdbeff6"
    )


def test_uninitialized(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "get_config_dir", lambda: tmp_path)
    with pytest.raises(ConfigurationError, match="Deployment has not been initialized"):
        load_deployment_state()


@pytest.mark.parametrize(
    "name",
    ["deployment_id", "voprf_key_version", "voprf_public_key"],
)
def test_missing_config(tmp_path, monkeypatch, name):
    with pytest.raises(ConfigurationError, match="Deployment configuration is invalid"):
        persisted_state(tmp_path, monkeypatch, omitted=(name,))


@pytest.mark.parametrize(
    "deployment_id",
    [
        "8d96fc18-f40f-4ec7-8ae8-f3711d88b741",
        "URN:UUID:8d96fc18-f40f-4ec7-8ae8-f3711d88b741",
        "urn:uuid:8D96FC18-F40F-4EC7-8AE8-F3711D88B741",
        "urn:uuid:not-a-uuid",
    ],
)
def test_invalid_persisted_deployment_id(tmp_path, monkeypatch, deployment_id):
    with pytest.raises(ConfigurationError):
        persisted_state(tmp_path, monkeypatch, deployment_id=deployment_id)


@pytest.mark.parametrize("version", [0, -1, MAX_KEY_VERSION + 1, "1", True])
def test_invalid_persisted_key_version(tmp_path, monkeypatch, version):
    with pytest.raises(ConfigurationError):
        persisted_state(tmp_path, monkeypatch, voprf_key_version=version)


@pytest.mark.parametrize("version", [1, MAX_KEY_VERSION])
def test_key_version_boundaries(tmp_path, monkeypatch, version):
    assert persisted_state(tmp_path, monkeypatch, voprf_key_version=version).voprf_key_version == version


@pytest.mark.parametrize("public_key", [b"x" * 31, b"x" * 33, b"\x00" * 32, b"\xff" * 32])
def test_invalid_public_key(tmp_path, monkeypatch, public_key):
    with pytest.raises(ConfigurationError):
        persisted_state(tmp_path, monkeypatch, public_key=public_key)


@pytest.mark.parametrize(
    "value",
    ["", "not+base64url", "a" * 42 + "=", " a" * 21 + "a"],
)
def test_invalid_public_key_encoding(tmp_path, monkeypatch, value):
    with pytest.raises(ConfigurationError):
        persisted_state(tmp_path, monkeypatch, encoded_public_key=value)


def test_noncanonical_public_key(tmp_path, monkeypatch):
    state = persisted_state(tmp_path, monkeypatch)
    encoded = base64.urlsafe_b64encode(
        state.voprf_server.public_key
    ).rstrip(b"=").decode("ascii")
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    replacement = alphabet[alphabet.index(encoded[-1]) + 1]
    with pytest.raises(ConfigurationError):
        persisted_state(
            tmp_path,
            monkeypatch,
            encoded_public_key=encoded[:-1] + replacement,
        )


def test_missing_and_invalid_private_key(tmp_path, monkeypatch):
    state = persisted_state(tmp_path, monkeypatch)
    assert state.voprf_server.public_key
    config_module.get_private_key_path().unlink()
    with pytest.raises(ConfigurationError):
        load_deployment_state()


@pytest.mark.parametrize(
    "private_key",
    [b"x" * 31, b"x" * 33, b"\x00" * 32, b"\xff" * 32],
)
def test_invalid_private_key(tmp_path, monkeypatch, private_key):
    with pytest.raises(ConfigurationError):
        persisted_state(tmp_path, monkeypatch, private_key=private_key)


def test_private_key_directory(tmp_path, monkeypatch):
    persisted_state(tmp_path, monkeypatch)
    path = config_module.get_private_key_path()
    path.unlink()
    path.mkdir()
    with pytest.raises(ConfigurationError):
        load_deployment_state()


def test_key_mismatch(tmp_path, monkeypatch):
    other = tmp_path / "other.key"
    other.write_bytes(b"\x02" + b"\x00" * 31)
    with pytest.raises(ConfigurationError, match="Configured VOPRF keys do not match"):
        persisted_state(tmp_path, monkeypatch, public_key=VOPRFServer(other).public_key)


@pytest.mark.parametrize(
    "field,minimum,maximum",
    [
        ("voprf_max_concurrency", 1, 64),
        ("voprf_evaluation_timeout_ms", 1, 60_000),
        ("assertion_evaluation_max_concurrency", 1, 64),
        ("assertion_evaluation_timeout_ms", 1, 60_000),
    ],
)
def test_resource_control_boundaries(tmp_path, field, minimum, maximum):
    key = tmp_path / "key"
    key.write_bytes(PRIVATE_KEY)
    values = {
        "deployment_id": DEPLOYMENT_ID,
        "voprf_key_version": 1,
        "voprf_public_key": VOPRFServer(key).public_key,
        "voprf_private_key_file": key,
    }
    for value in (minimum, maximum):
        assert getattr(DeploymentConfig(**values, **{field: value}), field) == value


@pytest.mark.parametrize(
    "field,minimum,maximum",
    [
        ("voprf_max_concurrency", 1, 64),
        ("voprf_evaluation_timeout_ms", 1, 60_000),
        ("assertion_evaluation_max_concurrency", 1, 64),
        ("assertion_evaluation_timeout_ms", 1, 60_000),
    ],
)
def test_invalid_resource_controls(tmp_path, field, minimum, maximum):
    key = tmp_path / "key"
    key.write_bytes(PRIVATE_KEY)
    values = {
        "deployment_id": DEPLOYMENT_ID,
        "voprf_key_version": 1,
        "voprf_public_key": VOPRFServer(key).public_key,
        "voprf_private_key_file": key,
    }
    for value in (minimum - 1, maximum + 1, True, float(minimum)):
        with pytest.raises(ConfigurationError):
            DeploymentConfig(**values, **{field: value})


def test_config_repr_and_immutability(tmp_path, monkeypatch):
    state = persisted_state(tmp_path, monkeypatch)
    config = DeploymentConfig(
        deployment_id=DEPLOYMENT_ID,
        voprf_key_version=1,
        voprf_public_key=state.voprf_server.public_key,
        voprf_private_key_file=config_module.get_private_key_path(),
    )
    for value in (
        PRIVATE_KEY.hex(),
        str(config_module.get_private_key_path()),
        base64.urlsafe_b64encode(state.voprf_server.public_key).decode("ascii"),
    ):
        assert value not in repr(config)
        assert value not in repr(state)
    with pytest.raises(FrozenInstanceError):
        state.voprf_key_version = 2


def test_error_secrecy(tmp_path, monkeypatch):
    marker = "secret-marker"
    with pytest.raises(ConfigurationError) as failure:
        persisted_state(
            tmp_path,
            monkeypatch,
            encoded_public_key=marker,
        )
    assert marker not in str(failure.value)
