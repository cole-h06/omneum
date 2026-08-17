"""
Omneum Ping Tool.

Provides a health check for MCP clients.
"""

from omneum.config import (
    ALGORITHM_VERSION,
    PROTOCOL_VERSION,
    VOPRF_MODE,
    DeploymentState,
)
from omneum.linkage import ENCODING_VERSION
from omneum.oprf import CIPHERSUITE


async def handle_ping(
    state: DeploymentState,
) -> dict[str, str | int]:
    """
    Return the current server status.
    """

    return {
        "status": "ok",
        "protocol_version": PROTOCOL_VERSION,
        "algorithm_version": ALGORITHM_VERSION,
        "deployment_id": state.deployment_id,
        "voprf_key_version": state.voprf_key_version,
        "voprf_mode": VOPRF_MODE,
        "voprf_ciphersuite": CIPHERSUITE,
        "linkage_encoding_version": ENCODING_VERSION,
        "configuration_fingerprint": (
            state.configuration_fingerprint
        ),
    }
