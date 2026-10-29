import tomllib
import os
import tempfile

from dataclasses import dataclass
from pathlib import Path

from omneum.paths import get_config_dir


@dataclass
class DeploymentConfig:
    deployment_id: str
    voprf_key_version: int
    voprf_public_key: str


def get_config_path() -> Path:
    return get_config_dir() / "config.toml"


def save_config(config: DeploymentConfig) -> None:
    path = get_config_path()

    toml = f'''deployment_id = "{config.deployment_id}"
voprf_key_version = {config.voprf_key_version}
voprf_public_key = "{config.voprf_public_key}"
'''

    # Publish complete, flushed bytes without replacing an existing pin. An
    # exclusive open alone exposes an empty/partial pin to another initializer
    # and can strand it after a failed write. link() is atomic and no-clobber.
    descriptor, temporary = tempfile.mkstemp(prefix=".config-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(toml)
            file.flush()
            os.fsync(file.fileno())
        os.link(temporary, path, follow_symlinks=False)
    finally:
        os.unlink(temporary)


def load_config() -> DeploymentConfig:
    path = get_config_path()

    with path.open("rb") as f:
        data = tomllib.load(f)

    return DeploymentConfig(
        deployment_id=data["deployment_id"],
        voprf_key_version=data["voprf_key_version"],
        voprf_public_key=data["voprf_public_key"],
    )
