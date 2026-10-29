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

    # mkdir(parents=True) applies mode only to the leaf. A umask of 0002
    # otherwise creates writable configuration ancestors on a fresh account.
    from .storage.filesystem import private_directory
    with private_directory(path, create=True, ancestor=True):
        pass
    return path


def get_context_db_path() -> Path:
    """Resolve the native user-data location without creating directories/files."""
    if sys.platform == "darwin":
        directory = Path.home() / "Library" / "Application Support" / "Omneum"
    elif sys.platform == "win32":
        local_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_data) if local_data and Path(local_data).is_absolute() else Path.home() / "AppData" / "Local"
        directory = base / "Omneum"
        return directory / "omneum.db"
    else:
        xdg_data = os.environ.get("XDG_DATA_HOME")
        # The XDG specification requires an absolute path; ignore relative values.
        base = Path(xdg_data) if xdg_data and Path(xdg_data).is_absolute() else Path.home() / ".local" / "share"
        directory = base / "omneum"
        if xdg_data and Path(xdg_data).is_absolute():
            return directory / "omneum.db"
    # Existing data and explicit locations must never be silently redirected.
    # A fallback remains stable after another tool repairs the native ancestors.
    fallback = Path.home() / ".omneum" / "data"
    native_exists = os.path.lexists(directory)
    fallback_exists = os.path.lexists(fallback)
    if native_exists and fallback_exists:
        raise ValueError("multiple local Context Graph locations require explicit selection")
    if native_exists:
        return directory / "omneum.db"
    if fallback_exists:
        return fallback / "omneum.db"
    from .storage.filesystem import private_directory
    parent = directory.parent
    while not os.path.lexists(parent):
        parent = parent.parent
    try:
        with private_directory(parent, ancestor=True):
            pass
    except ValueError:
        # Do not chmod shared Python/data directories. The storage adapter still
        # validates every fallback ancestor and creates only private directories.
        directory = fallback
    return directory / "omneum.db"
