import os
import sys
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from mcp import StdioServerParameters

from verity import VerityClientConfig
from verity.base64url import encode_unpadded
from verity.oprf import VOPRFServer


DEPLOYMENT_ID = "urn:uuid:8d96fc18-f40f-4ec7-8ae8-f3711d88b741"
# Scalar 1 is a deterministic example key. Never use it in production.
PRIVATE_KEY = b"\x01" + b"\x00" * 31


@contextmanager
def example_deployment():
    root = Path(__file__).parents[2]
    with TemporaryDirectory(prefix="verity-example-") as directory:
        private_key_file = Path(directory) / "voprf.key"
        private_key_file.write_bytes(PRIVATE_KEY)
        public_key = VOPRFServer(private_key_file).public_key
        environment = {
            **os.environ,
            "PYTHONPATH": str(root),
            "VERITY_DEPLOYMENT_ID": DEPLOYMENT_ID,
            "VERITY_VOPRF_KEY_VERSION": "1",
            "VERITY_VOPRF_PUBLIC_KEY": encode_unpadded(
                public_key,
                expected_length=32,
            ),
            "VERITY_VOPRF_PRIVATE_KEY_FILE": str(private_key_file),
        }
        config = VerityClientConfig(
            deployment_id=DEPLOYMENT_ID,
            voprf_key_version=1,
            voprf_mode="voprf",
            voprf_ciphersuite="ristretto255-SHA512",
            linkage_encoding_version=1,
            voprf_public_key=public_key,
        )
        server = StdioServerParameters(
            command=sys.executable,
            args=["-m", "verity.server"],
            cwd=root,
            env=environment,
        )
        yield config, server
