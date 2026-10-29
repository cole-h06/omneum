"""Disposable same-UID benchmark deployment; its fixed key is test-only."""

import base64
from contextlib import contextmanager
from functools import cache
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from omneum.mcp import StdioServerParameters
from omneum import OmneumClientConfig
from omneum.config import VOPRF_MODE
from omneum.daemon import DaemonServerContext, DaemonUnavailableError
from omneum.linkage import ENCODING_VERSION
from omneum.oprf import CIPHERSUITE


ROOT = Path(__file__).resolve().parents[2]
DEPLOYMENT_ID = "urn:uuid:00000000-0000-4000-8000-000000000001"
TEST_KEY = b"\x02" + b"\x00" * 31


@cache
def _build_daemon():
    target = ROOT / "target/test-daemon"
    subprocess.run(
        ["cargo", "build", "--locked", "--no-default-features",
         "--features", "test-daemon", "--bin", "omneumd",
         "--target-dir", str(target)],
        cwd=ROOT, check=True, capture_output=True,
    )
    return target / "debug/omneumd"


def _public_key(process, socket_path):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Benchmark daemon exited during startup.")
        try:
            return DaemonServerContext.fetch_public_key(
                socket_path, os.getuid(), timeout=.2,
            )
        except (DaemonUnavailableError, TimeoutError):
            time.sleep(.01)
    raise RuntimeError("Benchmark daemon startup timed out.")


@contextmanager
def benchmark_deployment():
    binary = _build_daemon()
    # Resolve macOS's temporary-directory symlinks for daemon path validation.
    with tempfile.TemporaryDirectory(
        prefix="ob-", dir=Path(tempfile.gettempdir()).resolve(),
    ) as directory:
        root = Path(directory)
        key_dir = root / "keys"
        key_dir.mkdir(mode=0o700)
        key_file = key_dir / "voprf.key"
        key_file.write_bytes(TEST_KEY)
        key_file.chmod(0o600)
        socket_path = root / "eval.sock"
        process = subprocess.Popen(
            [str(binary), "serve", "--test-mode", "--key-dir", str(key_dir),
             "--socket", str(socket_path), "--client-uid", str(os.getuid()),
             "--rate", "100000", "--burst", "100000"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            public_key = _public_key(process, socket_path)
            config = OmneumClientConfig(
                deployment_id=DEPLOYMENT_ID,
                voprf_key_version=1,
                voprf_mode=VOPRF_MODE,
                voprf_ciphersuite=CIPHERSUITE,
                linkage_encoding_version=ENCODING_VERSION,
                voprf_public_key=public_key,
            )
            config_dir = root / "config"
            config_dir.mkdir(mode=0o700)
            encoded = base64.urlsafe_b64encode(public_key).rstrip(b"=").decode("ascii")
            (config_dir / "config.toml").write_text(
                f'deployment_id = "{DEPLOYMENT_ID}"\n'
                'voprf_key_version = 1\n'
                f'voprf_public_key = "{encoded}"\n',
                encoding="utf-8",
            )
            environment = {
                name: value for name, value in os.environ.items()
                if not name.startswith("OMNEUM_")
            }
            environment.update(
                PYTHONPATH=str(ROOT),
                OMNEUM_CONFIG_DIR=str(config_dir),
                OMNEUM_DAEMON_SOCKET=str(socket_path),
                OMNEUM_DAEMON_UID=str(os.getuid()),
            )
            yield config, StdioServerParameters(
                command=sys.executable, args=["-m", "omneum.server"],
                cwd=ROOT, env=environment,
            )
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
