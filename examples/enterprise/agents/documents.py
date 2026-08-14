import json
from pathlib import Path

from .common import POLICY_SOURCE, RUNBOOK_SOURCE, observation


DATA = Path(__file__).parents[1] / "data"


def documents_agent():
    """Retrieve the current policy and stale deployment runbook."""

    observations = []

    policy = json.loads(
        (DATA / "ai_data_governance_policy.json").read_text(encoding="utf-8")
    )
    observations.extend(
        _policy_observations(policy)
    )

    runbook = json.loads(
        (DATA / "copilot_deployment_runbook.json").read_text(encoding="utf-8")
    )
    observations.extend(
        _runbook_observations(runbook)
    )

    return tuple(observations)


def _policy_observations(policy):
    controls = {
        control["control_id"]: control
        for control in policy["controls"]
    }

    return (
        observation(
            "policy-input-data",
            POLICY_SOURCE,
            controls["input-data-policy"]["name"],
            controls["input-data-policy"]["setting"],
            policy["document"]["last_updated"],
        ),
        observation(
            "policy-retention",
            POLICY_SOURCE,
            controls["provider-retention"]["name"],
            f'{controls["provider-retention"]["setting"]}',
            policy["document"]["last_updated"],
        ),
        observation(
            "policy-region",
            POLICY_SOURCE,
            controls["processing-region"]["name"],
            controls["processing-region"]["setting"],
            policy["document"]["last_updated"],
        ),
    )


def _runbook_observations(runbook):
    controls = {
        control["control_id"]: control
        for control in runbook["deployment_controls"]
    }

    return (
        observation(
            "runbook-input-data",
            RUNBOOK_SOURCE,
            controls["input-data-policy"]["name"],
            controls["input-data-policy"]["setting"],
            runbook["document"]["published_at"],
        ),
        observation(
            "runbook-retention",
            RUNBOOK_SOURCE,
            controls["provider-retention"]["name"],
            controls["provider-retention"]["setting"],
            runbook["document"]["published_at"],
        ),
        observation(
            "runbook-region",
            RUNBOOK_SOURCE,
            controls["processing-region"]["name"],
            controls["processing-region"]["setting"],
            runbook["document"]["published_at"],
        ),
    )
