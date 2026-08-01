from __future__ import annotations

import asyncio
import os
from pathlib import Path

from mcp import StdioServerParameters

from verity.base64url import encode_unpadded
from verity.client import VerityClientConfig, open_stdio_client
from verity.oprf import VOPRFServer


DEPLOYMENT_ID = "urn:uuid:8d96fc18-f40f-4ec7-8ae8-f3711d88b741"
PRIVATE_KEY = b"\x01" + b"\x00" * 31


def test_sdk_end_to_end_over_real_stdio(tmp_path: Path) -> None:
    async def run() -> None:
        root = Path(__file__).parents[1]
        private_key_file = tmp_path / "voprf.key"
        private_key_file.write_bytes(PRIVATE_KEY)
        public_key = VOPRFServer(private_key_file).public_key
        environment = {
            **os.environ,
            "PYTHONPATH": str(root),
            "VERITY_DEPLOYMENT_ID": DEPLOYMENT_ID,
            "VERITY_VOPRF_KEY_VERSION": "1",
            "VERITY_VOPRF_PUBLIC_KEY": encode_unpadded(
                public_key, expected_length=32
            ),
            "VERITY_VOPRF_PRIVATE_KEY_FILE": str(private_key_file),
        }
        parameters = StdioServerParameters(
            command=str(root / ".venv/bin/python"),
            args=["-m", "verity.server"],
            cwd=root,
            env=environment,
        )
        config = VerityClientConfig(
            deployment_id=DEPLOYMENT_ID,
            voprf_key_version=1,
            voprf_mode="voprf",
            voprf_ciphersuite="ristretto255-SHA512",
            linkage_encoding_version=1,
            voprf_public_key=public_key,
        )
        async with open_stdio_client(config, parameters) as client:
            first = await client.link_claim(
                "service", " Example ", " Display Name ", " Alice "
            )
            second = await client.link_claim(
                "service", "example", "display_name", "Alice"
            )
            assert len(first.value) == 64
            assert first.value == second.value

    asyncio.run(run())
