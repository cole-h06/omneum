import tomllib

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

    # Initialization must not replace an existing public-key pin, even when
    # two init processes reach this write concurrently.
    with path.open("x", encoding="utf-8") as file:
        file.write(toml)


def load_config() -> DeploymentConfig:
    path = get_config_path()

    with path.open("rb") as f:
        data = tomllib.load(f)

    return DeploymentConfig(
        deployment_id=data["deployment_id"],
        voprf_key_version=data["voprf_key_version"],
        voprf_public_key=data["voprf_public_key"],
    )