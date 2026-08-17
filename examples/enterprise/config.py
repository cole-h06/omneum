import os
import sys
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from mcp import StdioServerParameters

from omneum import OmneumClientConfig
from omneum.base64url import encode_unpadded
from omneum.oprf import VOPRFServer


DEPLOYMENT_ID = "urn:uuid:8d96fc18-f40f-4ec7-8ae8-f3711d88b741"
# Scalar 1 is a deterministic example key. Never use it in production.
PRIVATE_KEY = b"\x01" + b"\x00" * 31


@contextmanager
def example_deployment():
    root = Path(__file__).parents[2]
    with TemporaryDirectory(prefix="omneum-example-") as directory:
        home = Path(directory) / "home"
        config_dir = home / ".config" / "Omneum"
        private_key_file = config_dir / "keys" / "voprf.key"
        private_key_file.parent.mkdir(parents=True)
        private_key_file.write_bytes(PRIVATE_KEY)
        public_key = VOPRFServer(private_key_file).public_key
        environment = {
            **os.environ,
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "LOCALAPPDATA": str(home / "AppData" / "Local"),
            "PYTHONPATH": str(root),
        }
        for name in tuple(environment):
            if name.startswith("OMNEUM_"):
                del environment[name]
        (config_dir / "config.toml").write_text(
            f'deployment_id = "{DEPLOYMENT_ID}"\n'
            'voprf_key_version = 1\n'
            f'voprf_public_key = "{encode_unpadded(public_key, expected_length=32)}"\n'
        )
        config = OmneumClientConfig(
            deployment_id=DEPLOYMENT_ID,
            voprf_key_version=1,
            voprf_mode="voprf",
            voprf_ciphersuite="ristretto255-SHA512",
            linkage_encoding_version=1,
            voprf_public_key=public_key,
        )
        server = StdioServerParameters(
            command=sys.executable,
            args=["-m", "omneum.server"],
            cwd=root,
            env=environment,
        )
        yield config, server
