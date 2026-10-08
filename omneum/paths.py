import os
import sys
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

    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def get_context_db_path() -> Path:
    """Resolve the native user-data location without creating directories/files."""
    if sys.platform == "darwin":
        directory = Path.home() / "Library" / "Application Support" / "Omneum"
    elif sys.platform == "win32":
        local_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_data) if local_data and Path(local_data).is_absolute() else Path.home() / "AppData" / "Local"
        directory = base / "Omneum"
    else:
        xdg_data = os.environ.get("XDG_DATA_HOME")
        # The XDG specification requires an absolute path; ignore relative values.
        base = Path(xdg_data) if xdg_data and Path(xdg_data).is_absolute() else Path.home() / ".local" / "share"
        directory = base / "omneum"
    return directory / "context.db"
