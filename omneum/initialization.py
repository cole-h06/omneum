"""Shared public configuration initialization for init and install."""

from .daemon import DaemonServerContext, get_daemon_socket, get_daemon_uid
from .deployment import DeploymentConfig, save_config
from .keys import encode_public_key
from .oprf import VOPRFClient
from .paths import get_config_dir
from .provision import generate_deployment_id


class InitializationError(Exception):
    pass


def initialize(public_key_hex: str | None = None) -> DeploymentConfig | None:
    """Return a new configuration, or None if a pin already exists. Never replace it."""
    if (get_config_dir() / "config.toml").exists():
        return None
    deployment_id = generate_deployment_id()
    try:
        if public_key_hex is None:
            public_key = DaemonServerContext.fetch_public_key(get_daemon_socket(), get_daemon_uid())
        else:
            public_key = bytes.fromhex(public_key_hex)
            VOPRFClient(public_key)
            DaemonServerContext(get_daemon_socket(), get_daemon_uid(), public_key)
    except Exception:
        raise InitializationError("Unable to verify the provisioned daemon public key.") from None
    config = DeploymentConfig(deployment_id, 1, encode_public_key(public_key))
    try:
        save_config(config)
    except FileExistsError:
        return None
    return config
