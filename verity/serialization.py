import math

import orjson
import rfc8785

from typing import Any


MAX_INTEGER = (1 << 53) - 1
MAX_NESTING_DEPTH = 32
MAX_VALUE_NODES = 4_096
MAX_LINKAGE_PAYLOAD_SIZE = 65_517


def serialize_assertion(
    assertion: dict[str, Any],
) -> bytes:
    """
    Serializes a canonical assertion into a deterministic
    JSON byte sequence.
    """

    return orjson.dumps(
        assertion,
        option=(
            orjson.OPT_SORT_KEYS
        ),
    )


def serialize_source(
    kind: str,
    identifier: str,
) -> bytes:
    _validate_string(kind)
    _validate_string(identifier)
    payload = {
        "kind": kind,
        "identifier": identifier,
    }
    return _serialize_linkage(payload)


def serialize_attribute(
    entity_namespace: str,
    entity: str,
    attribute: str,
) -> bytes:
    _validate_string(entity_namespace)
    _validate_string(entity)
    _validate_string(attribute)
    payload = {
        "entity_namespace": entity_namespace,
        "entity": entity,
        "attribute": attribute,
    }
    return _serialize_linkage(payload)


def serialize_claim(
    entity_namespace: str,
    entity: str,
    attribute: str,
    value: Any,
) -> bytes:
    _validate_string(entity_namespace)
    _validate_string(entity)
    _validate_string(attribute)
    _validate_value(value)
    payload = {
        "entity_namespace": entity_namespace,
        "entity": entity,
        "attribute": attribute,
        "value": value,
    }
    try:
        return _serialize_linkage(payload)
    except rfc8785.CanonicalizationError:
        raise ValueError("claim value is invalid") from None


def _serialize_linkage(
    payload: dict[str, Any],
) -> bytes:
    serialized = rfc8785.dumps(payload)

    if len(serialized) > MAX_LINKAGE_PAYLOAD_SIZE:
        raise ValueError(
            "serialized linkage payload is too large"
        )

    return serialized


def _validate_value(
    value: Any,
    depth: int = 0,
    nodes: list[int] | None = None,
) -> None:
    if nodes is None:
        nodes = [0]

    nodes[0] += 1

    if nodes[0] > MAX_VALUE_NODES:
        raise ValueError(
            "value contains too many nodes"
        )

    if value is None or type(value) is bool:
        return

    if type(value) is int:
        if not -MAX_INTEGER <= value <= MAX_INTEGER:
            raise ValueError(
                "integer is outside the safe range"
            )
        return

    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(
                "value cannot be NaN or infinite"
            )
        return

    if type(value) is str:
        _validate_string(value)
        return

    if type(value) is list:
        if depth >= MAX_NESTING_DEPTH:
            raise ValueError(
                "value exceeds maximum nesting depth"
            )

        for item in value:
            _validate_value(
                item,
                depth + 1,
                nodes,
            )
        return

    if type(value) is dict:
        if depth >= MAX_NESTING_DEPTH:
            raise ValueError(
                "value exceeds maximum nesting depth"
            )

        for key, item in value.items():
            if type(key) is not str:
                raise TypeError(
                    "object keys must be strings"
                )
            _validate_string(key)
            _validate_value(
                item,
                depth + 1,
                nodes,
            )
        return

    raise TypeError(
        "value must be a supported JSON data type"
    )


def _validate_string(value: str) -> None:
    if type(value) is not str:
        raise TypeError(
            "linkage fields must be strings"
        )

    if any(
        0xD800 <= ord(character) <= 0xDFFF
        for character in value
    ):
        raise ValueError(
            "strings cannot contain lone surrogates"
        )
