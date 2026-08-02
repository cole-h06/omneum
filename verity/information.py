from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .canonicalization import canonicalize_value


def _string(value, name):
    if type(value) is not str:
        raise TypeError(f"{name} must be a string")
    if not value:
        raise ValueError(f"{name} must not be empty")


def _optional_string(value, name):
    if value is not None:
        _string(value, name)


def _strings(value, name):
    if value is None:
        return
    if type(value) is not tuple:
        raise TypeError(f"{name} must be a tuple or None")
    for item in value:
        _string(item, name)


@dataclass(frozen=True, slots=True)
class Source:
    kind: str
    identifier: str
    owner_id: str | None = None

    def __post_init__(self):
        _string(self.kind, "kind")
        _string(self.identifier, "identifier")
        _optional_string(self.owner_id, "owner_id")


@dataclass(frozen=True, slots=True)
class SourceReference:
    kind: str
    identifier: str

    def __post_init__(self):
        _string(self.kind, "kind")
        _string(self.identifier, "identifier")


@dataclass(frozen=True, slots=True)
class Claim:
    entity_namespace: str
    entity: str
    attribute: str
    value: Any

    def __post_init__(self):
        _string(self.entity_namespace, "entity_namespace")
        _string(self.entity, "entity")
        _string(self.attribute, "attribute")
        canonicalize_value(self.value)


@dataclass(frozen=True, slots=True)
class Observation:
    assertion_id: str
    source: SourceReference
    claim: Claim
    source_timestamp: datetime | None
    provenance_ids: tuple[str, ...] | None
    cited_sources: tuple[SourceReference, ...] | None = None
    parent_assertion_ids: tuple[str, ...] | None = None

    def __post_init__(self):
        _string(self.assertion_id, "assertion_id")
        if type(self.source) is not SourceReference:
            raise TypeError("source must be a SourceReference")
        if type(self.claim) is not Claim:
            raise TypeError("claim must be a Claim")
        if self.source_timestamp is not None:
            if type(self.source_timestamp) is not datetime:
                raise TypeError("source_timestamp must be a datetime or None")
            if (
                self.source_timestamp.tzinfo is None
                or self.source_timestamp.utcoffset() is None
            ):
                raise ValueError("source_timestamp must be timezone-aware")
        _strings(self.provenance_ids, "provenance_ids")
        if self.cited_sources is not None:
            if type(self.cited_sources) is not tuple:
                raise TypeError("cited_sources must be a tuple or None")
            for source in self.cited_sources:
                if type(source) is not SourceReference:
                    raise TypeError(
                        "cited_sources must contain SourceReference values"
                    )
        _strings(self.parent_assertion_ids, "parent_assertion_ids")
