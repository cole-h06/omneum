from examples.enterprise.workflow.run import collect_observations


def initial_observations(scenario: str):
    observations = collect_observations()

    if scenario == "diversify_sources":
        return observations

    if scenario == "retrieve_support":
        return tuple(
            item for item in observations
            if item.claim.attribute != "processing_region"
        )

    if scenario == "resolve_conflicts":
        return tuple(
            item for item in observations
            if item.source.owner_id in {
                "risk-and-compliance",
                "ai-platform",
            }
        )

    raise ValueError(f"Unknown routing scenario: {scenario}")
