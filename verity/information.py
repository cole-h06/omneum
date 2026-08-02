from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import orjson
import rfc8785

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


def _value_type(value):
    if value is None or type(value) in (bool, int, float, str):
        return
    if type(value) is list:
        for item in value:
            _value_type(item)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError("claim object keys must be strings")
            _value_type(item)
        return
    raise TypeError("claim value must use exact JSON types")


@dataclass(frozen=True, slots=True)
class Source:
    kind: str
    identifier: str = field(repr=False)
    owner_id: str | None = field(default=None, repr=False)

    def __post_init__(self):
        _string(self.kind, "kind")
        _string(self.identifier, "identifier")
        _optional_string(self.owner_id, "owner_id")


@dataclass(frozen=True, slots=True)
class SourceReference:
    kind: str
    identifier: str = field(repr=False)

    def __post_init__(self):
        _string(self.kind, "kind")
        _string(self.identifier, "identifier")


@dataclass(frozen=True, slots=True, init=False)
class Claim:
    entity_namespace: str = field(repr=False)
    entity: str = field(repr=False)
    attribute: str = field(repr=False)
    _value_bytes: bytes = field(repr=False)

    def __init__(self, entity_namespace, entity, attribute, value):
        _string(entity_namespace, "entity_namespace")
        _string(entity, "entity")
        _string(attribute, "attribute")
        _value_type(value)
        canonical = canonicalize_value(value)
        try:
            value_bytes = rfc8785.dumps(canonical)
        except rfc8785.CanonicalizationError:
            raise ValueError("claim value is invalid") from None
        object.__setattr__(self, "entity_namespace", entity_namespace)
        object.__setattr__(self, "entity", entity)
        object.__setattr__(self, "attribute", attribute)
        object.__setattr__(self, "_value_bytes", value_bytes)

    @property
    def value(self) -> Any:
        return orjson.loads(self._value_bytes)


@dataclass(frozen=True, slots=True)
class Observation:
    assertion_id: str = field(repr=False)
    source: Source = field(repr=False)
    claim: Claim = field(repr=False)
    source_timestamp: datetime | None = field(repr=False)
    provenance_ids: tuple[str, ...] | None = field(repr=False)
    cited_sources: tuple[SourceReference, ...] | None = field(
        default=None,
        repr=False,
    )
    parent_assertion_ids: tuple[str, ...] | None = field(
        default=None,
        repr=False,
    )

    def __post_init__(self):
        _string(self.assertion_id, "assertion_id")
        if type(self.source) is not Source:
            raise TypeError("source must be a Source")
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
