from pathlib import Path

from platformdirs import user_config_path


_APP_NAME = "Verity"


def get_config_dir() -> Path:
    path = user_config_path(_APP_NAME)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_key_dir() -> Path:
    path = get_config_dir() / "keys"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_private_key_path() -> Path:
    return get_key_dir() / "voprf.key"