"""Construct dated observations for synthetic adversarial fixtures."""
from datetime import datetime, timezone

from omneum import Observation


def observation(
    assertion_id,
    source,
    claim,
    date,
    *,
    source_modified_date=None,
    upstream_sources=(),
    cited_sources=(),
    parent_assertion_ids=(),
):
    observed_at = datetime.fromisoformat(date).replace(
        tzinfo=timezone.utc
    )
    source_modified_at = datetime.fromisoformat(
        source_modified_date or date
    ).replace(tzinfo=timezone.utc)

    return Observation(
        observation_id=assertion_id,
        source=source,
        claim=claim,
        observed_at=observed_at,
        source_modified_at=source_modified_at,
        upstream_sources=tuple(upstream_sources),
        cited_sources=tuple(cited_sources),
        parent_observation_ids=tuple(parent_assertion_ids),
        retrievals=(),
    )
