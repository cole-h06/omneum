import os
from pathlib import Path

from platformdirs import user_config_path


_APP_NAME = "Omneum"
_CONFIG_DIR_ENV = "OMNEUM_CONFIG_DIR"


def get_config_dir() -> Path:
    override = os.environ.get(_CONFIG_DIR_ENV)

    if override:
        path = Path(override).expanduser()
    else:
        path = user_config_path(_APP_NAME)

    path.mkdir(parents=True, exist_ok=True)
    return path
