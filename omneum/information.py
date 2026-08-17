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


def _datetime(value, name, *, optional=False):
    if value is None:
        if optional:
            return
        raise TypeError(f"{name} must be a datetime")

    if type(value) is not datetime:
        suffix = " or None" if optional else ""
        raise TypeError(f"{name} must be a datetime{suffix}")

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


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


def _json_value_type(value):
    if value is None or type(value) in (bool, int, float, str):
        return
    if type(value) is list:
        for item in value:
            _json_value_type(item)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError("retrieval field keys must be strings")
            _json_value_type(item)
        return
    raise TypeError("retrieval fields must use exact JSON types")


def _snapshot_json(value):
    if type(value) is list:
        return [_snapshot_json(item) for item in value]
    if type(value) is dict:
        return {
            key: _snapshot_json(item)
            for key, item in value.items()
        }
    return value


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
class Retrieval:
    retrieval_id: str = field(repr=False)
    kind: str
    resource_id: str = field(repr=False)
    retrieved_at: datetime = field(repr=False)
    fields: dict[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self):
        _string(self.retrieval_id, "retrieval_id")
        _string(self.kind, "kind")
        _string(self.resource_id, "resource_id")
        _datetime(self.retrieved_at, "retrieved_at")

        if type(self.fields) is not dict:
            raise TypeError("fields must be a dict")

        _json_value_type(self.fields)
        object.__setattr__(
            self,
            "fields",
            _snapshot_json(self.fields),
        )


@dataclass(frozen=True, slots=True)
class Observation:
    assertion_id: str = field(repr=False)
    source: Source = field(repr=False)
    claim: Claim = field(repr=False)
    observed_at: datetime = field(repr=False)
    source_modified_at: datetime | None = field(
        default=None,
        repr=False,
    )
    upstream_sources: tuple[SourceReference, ...] | None = field(
        default=None,
        repr=False,
    )
    cited_sources: tuple[SourceReference, ...] | None = field(
        default=None,
        repr=False,
    )
    parent_assertion_ids: tuple[str, ...] | None = field(
        default=None,
        repr=False,
    )
    retrievals: tuple[Retrieval, ...] | None = field(
        default=None,
        repr=False,
    )

    def __post_init__(self):
        _string(self.assertion_id, "assertion_id")

        if type(self.source) is not Source:
            raise TypeError("source must be a Source")

        if type(self.claim) is not Claim:
            raise TypeError("claim must be a Claim")

        _datetime(self.observed_at, "observed_at")
        _datetime(
            self.source_modified_at,
            "source_modified_at",
            optional=True,
        )

        if self.upstream_sources is not None:
            if type(self.upstream_sources) is not tuple:
                raise TypeError(
                    "upstream_sources must be a tuple or None"
                )
            for source in self.upstream_sources:
                if type(source) is not SourceReference:
                    raise TypeError(
                        "upstream_sources must contain "
                        "SourceReference values"
                    )

        if self.cited_sources is not None:
            if type(self.cited_sources) is not tuple:
                raise TypeError(
                    "cited_sources must be a tuple or None"
                )
            for source in self.cited_sources:
                if type(source) is not SourceReference:
                    raise TypeError(
                        "cited_sources must contain "
                        "SourceReference values"
                    )

        _strings(
            self.parent_assertion_ids,
            "parent_assertion_ids",
        )

        if self.retrievals is not None:
            if type(self.retrievals) is not tuple:
                raise TypeError(
                    "retrievals must be a tuple or None"
                )
            for retrieval in self.retrievals:
                if type(retrieval) is not Retrieval:
                    raise TypeError(
                        "retrievals must contain Retrieval values"
                    )
