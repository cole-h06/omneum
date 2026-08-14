import json
from pathlib import Path

from .common import BRIEF_SOURCE, RUNBOOK_SOURCE, observation, reference


FIXTURE = Path(__file__).parents[1] / "data" / "copilot_readiness_brief.json"


def research_agent():
    """Retrieve a readiness brief derived from the stale runbook."""

    brief = json.loads(FIXTURE.read_text(encoding="utf-8"))

    document = brief["document"]
    assessment = brief["deployment_assessment"]

    runbook = reference(RUNBOOK_SOURCE)

    return (
        observation(
            "brief-input-data",
            BRIEF_SOURCE,
            "Input Data Policy",
            assessment["input_data_policy"],
            document["generated_at"],
            (runbook,),
            ("runbook-input-data",),
        ),
        observation(
            "brief-retention",
            BRIEF_SOURCE,
            "Provider Retention",
            f'{assessment["provider_retention_days"]} days',
            document["generated_at"],
            (runbook,),
            ("runbook-retention",),
        ),
        observation(
            "brief-region",
            BRIEF_SOURCE,
            "Processing Region",
            assessment["processing_region"],
            document["generated_at"],
            (runbook,),
            ("runbook-region",),
        ),
    )
