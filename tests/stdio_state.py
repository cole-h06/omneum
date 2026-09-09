import base64
import os
from pathlib import Path
import subprocess
import sys

from daemon_support import FixtureDaemon


def isolated_deployment_environment(
    tmp_path: Path,
    deployment_id: str,
    private_key: bytes,
) -> tuple[dict[str, str], bytes, Path]:
    home = tmp_path / "home"
    environment = {
        **os.environ,
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / "config"),
        "APPDATA": str(home / "appdata"),
        "LOCALAPPDATA": str(home / "localappdata"),
        "PYTHONPATH": str(Path(__file__).parents[1]),
    }
    for name in tuple(environment):
        if name.startswith("OMNEUM_"):
            del environment[name]
    resolved = subprocess.run(
        [
            sys.executable,
            "-c",
            "from omneum.paths import get_config_dir; print(get_config_dir())",
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    config_dir = Path(resolved.stdout.strip())
    daemon = FixtureDaemon(private_key)
    _DAEMONS.append(daemon)
    environment["OMNEUM_DAEMON_SOCKET"] = str(daemon.socket)
    environment["OMNEUM_DAEMON_UID"] = str(os.getuid())
    public_key = daemon.public_key
    encoded = base64.urlsafe_b64encode(public_key).rstrip(b"=").decode("ascii")
    (config_dir / "config.toml").write_text(
        f'deployment_id = "{deployment_id}"\n'
        'voprf_key_version = 1\n'
        f'voprf_public_key = "{encoded}"\n'
    )
    return environment, public_key, config_dir / "config.toml"


_DAEMONS = []
