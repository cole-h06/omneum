from datetime import datetime

from omneum import Claim, Observation, Source, SourceReference


SCOPE = "7c710000-1234-4abc-8def-123456789abc"
ENTITY_NAMESPACE = "service"
ENTITY = "EU Customer Support Copilot"

POLICY_SOURCE = Source(
    "internal_resource",
    f"v1:{SCOPE}:00000001-0000-4000-8000-000000000001",
    "risk-and-compliance",
)
RUNBOOK_SOURCE = Source(
    "internal_resource",
    f"v1:{SCOPE}:00000002-0000-4000-8000-000000000002",
    "ai-platform",
)
BRIEF_SOURCE = Source(
    "internal_resource",
    f"v1:{SCOPE}:00000003-0000-4000-8000-000000000003",
    "ai-platform",
)
REGISTRY_SOURCE = Source(
    "database",
    f"v1:{SCOPE}:00000004-0000-4000-8000-000000000004",
    "model-governance",
)
GATEWAY_SOURCE = Source(
    "internal_service",
    f"v1:{SCOPE}:00000005-0000-4000-8000-000000000005",
    "ai-platform-operations",
)
VENDOR_SOURCE = Source(
    "web_document",
    "https://trust.example.ai/legal/enterprise-data-controls",
    "vendor-legal",
)


def observation(
    assertion_id,
    source,
    attribute,
    value,
    timestamp,
    cited_sources=(),
    parent_assertion_ids=(),
):
    modified_at = datetime.fromisoformat(timestamp)
    return Observation(
        assertion_id=assertion_id,
        source=source,
        claim=Claim(ENTITY_NAMESPACE, ENTITY, attribute, value),
        observed_at=modified_at,
        source_modified_at=modified_at,
        upstream_sources=(),
        cited_sources=tuple(cited_sources),
        parent_assertion_ids=tuple(parent_assertion_ids),
        retrievals=(),
    )


def reference(source):
    return SourceReference(source.kind, source.identifier)
