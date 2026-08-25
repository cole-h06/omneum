from datetime import datetime
from typing import Any

from .information import (
    Claim,
    Observation,
    Retrieval,
    Source,
    SourceReference,
)


def observe(
    *,
    assertion_id: str,
    source: Source,
    entity_namespace: str,
    entity: str,
    attribute: str,
    value: Any,
    observed_at: datetime,
    source_modified_at: datetime | None = None,
    upstream_sources: tuple[SourceReference, ...] | None = None,
    cited_sources: tuple[SourceReference, ...] | None = None,
    parent_assertion_ids: tuple[str, ...] | None = None,
    retrievals: tuple[Retrieval, ...] | None = None,
    metadata: dict[str, Any] | None = None,
    dependency_signals: dict[str, Any] | None = None,
) -> Observation:
    return Observation(
        assertion_id=assertion_id,
        source=source,
        claim=Claim(
            entity_namespace=entity_namespace,
            entity=entity,
            attribute=attribute,
            value=value,
        ),
        observed_at=observed_at,
        source_modified_at=source_modified_at,
        upstream_sources=upstream_sources,
        cited_sources=cited_sources,
        parent_assertion_ids=parent_assertion_ids,
        retrievals=retrievals,
        metadata={} if metadata is None else metadata,
        dependency_signals=(
            {}
            if dependency_signals is None
            else dependency_signals
        ),
    )


def retrieval(
    *,
    retrieval_id: str,
    kind: str,
    resource_id: str,
    retrieved_at: datetime,
    fields: dict[str, Any] | None = None,
) -> Retrieval:
    return Retrieval(
        retrieval_id=retrieval_id,
        kind=kind,
        resource_id=resource_id,
        retrieved_at=retrieved_at,
        fields={} if fields is None else fields,
    )


def reference(
    source: Source | None = None,
    *,
    kind: str | None = None,
    identifier: str | None = None,
) -> SourceReference:
    if source is not None:
        if kind is not None or identifier is not None:
            raise TypeError(
                "source cannot be combined with kind or identifier"
            )
        return SourceReference(
            kind=source.kind,
            identifier=source.identifier,
        )

    if kind is None or identifier is None:
        raise TypeError(
            "kind and identifier are required without source"
        )

    return SourceReference(
        kind=kind,
        identifier=identifier,
    )
