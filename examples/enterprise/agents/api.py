import json
from pathlib import Path

from .common import GATEWAY_SOURCE, REGISTRY_SOURCE, observation, reference


FIXTURE = Path(__file__).parents[1] / "data" / "ai_gateway.json"


def api_agent():
    """Read the live AI gateway control-plane configuration."""

    gateway = json.loads(FIXTURE.read_text(encoding="utf-8"))
    deployment = gateway["deployment"]
    runtime = gateway["runtime"]

    registry = reference(REGISTRY_SOURCE)

    return (
        observation(
            "gateway-input-data",
            GATEWAY_SOURCE,
            "Input Data Policy",
            runtime["input_data_policy"],
            deployment["last_updated"],
            (registry,),
            ("registry-input-data",),
        ),
        observation(
            "gateway-retention",
            GATEWAY_SOURCE,
            "Provider Retention",
            f'{runtime["provider_retention_days"]} days',
            deployment["last_updated"],
            (registry,),
            ("registry-retention",),
        ),
        observation(
            "gateway-region",
            GATEWAY_SOURCE,
            "Processing Region",
            runtime["processing_region"],
            deployment["last_updated"],
            (registry,),
            ("registry-region",),
        ),
    )
