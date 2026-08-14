import json
from pathlib import Path

from .common import POLICY_SOURCE, REGISTRY_SOURCE, observation, reference


FIXTURE = Path(__file__).parents[1] / "data" / "model_registry.json"


def sql_agent():
    """Query the governed model registry."""

    registry = json.loads(FIXTURE.read_text(encoding="utf-8"))

    deployment = registry["deployment"]
    configuration = registry["configuration"]
    policy = reference(POLICY_SOURCE)

    return (
        observation(
            "registry-input-data",
            REGISTRY_SOURCE,
            "Input Data Policy",
            configuration["input_data_policy"],
            deployment["approved_at"],
            (policy,),
            ("policy-input-data",),
        ),
        observation(
            "registry-retention",
            REGISTRY_SOURCE,
            "Provider Retention",
            f'{configuration["provider_retention_days"]} days',
            deployment["approved_at"],
            (policy,),
            ("policy-retention",),
        ),
        observation(
            "registry-region",
            REGISTRY_SOURCE,
            "Processing Region",
            configuration["processing_region"],
            deployment["approved_at"],
            (policy,),
            ("policy-region",),
        ),
    )
