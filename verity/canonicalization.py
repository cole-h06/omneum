import re
import unicodedata
import idna
import rfc3986
import math

from typing import Any


ENTITY_NAMESPACES = {
    "service": {
        "lowercase": True,
    },
}


def canonicalize_entity(
    entity_namespace: str,
    entity: str,
) -> str:
    """
    Converts an entity into its canonical form.
    """

    if not isinstance(entity, str):
        raise TypeError(
            "entity must be a string"
        )

    if entity_namespace not in ENTITY_NAMESPACES:
        raise ValueError(
            "unknown entity namespace"
        )

    entity = unicodedata.normalize(
        "NFC",
        entity,
    )

    entity = entity.strip()

    if not entity:
        raise ValueError(
            "entity cannot be empty"
        )

    if ENTITY_NAMESPACES[
        entity_namespace
    ]["lowercase"]:
        entity = entity.lower()

    return entity


def canonicalize_attribute(
    attribute: str,
) -> str:
    """
    Converts an attribute into its canonical form.
    """

    if not isinstance(attribute, str):
        raise TypeError(
            "attribute must be a string"
        )

    attribute = attribute.strip()

    if not attribute:
        raise ValueError(
            "attribute cannot be empty"
        )

    attribute = re.sub(
        r"\s+",
        " ",
        attribute,
    )

    attribute = attribute.lower()

    attribute = attribute.replace(
        " ",
        "_",
    )

    return attribute


def canonicalize_source(
    source_kind: str,
    source: str,
) -> str:
    """
    Converts a source identifier into its canonical form.
    """

    if not isinstance(source, str):
        raise TypeError(
            "source must be a string"
        )

    source = source.strip()

    if not source:
        raise ValueError(
            "source cannot be empty"
        )

    if source_kind == "web_publisher":

        uri = rfc3986.uri_reference(
            source
        )

        host = uri.host

        if host is None:
            host = source

        if uri.path not in (
            "",
            "/",
            None,
        ):
            raise ValueError(
                "web publisher identifiers cannot contain a path"
            )

        if uri.query:
            raise ValueError(
                "web publisher identifiers cannot contain a query"
            )

        if uri.fragment:
            raise ValueError(
                "web publisher identifiers cannot contain a fragment"
            )

        host = host.lower()

        if host.endswith("."):
            host = host[:-1]

        host = idna.encode(
            host,
            uts46=True,
        ).decode(
            "ascii"
        )

        return host

    if source_kind == "web_document":

        uri = (
            rfc3986
            .uri_reference(source)
            .normalize()
        )

        if (
            uri.scheme is None
            or uri.host is None
        ):
            raise ValueError(
                "invalid web document identifier"
            )

        scheme = uri.scheme.lower()

        host = idna.encode(
            uri.host.lower(),
            uts46=True,
        ).decode(
            "ascii"
        )

        port = uri.port

        if (
            scheme == "http"
            and port == 80
        ):
            port = None

        if (
            scheme == "https"
            and port == 443
        ):
            port = None

        authority = host

        if port is not None:
            authority = (
                f"{host}:{port}"
            )

        path = uri.path or "/"

        query = ""

        if uri.query:
            query = (
                f"?{uri.query}"
            )

        return (
            f"{scheme}://"
            f"{authority}"
            f"{path}"
            f"{query}"
        )

    raise ValueError(
        "unknown source kind"
    )


def canonicalize_value(
    value: Any,
) -> Any:
    """
    Converts a value into its canonical form + preserve its underlying data type.
    """

    if value is None:
        return None

    if isinstance(value, bool):
        return value

    if isinstance(value, int):
        return value

    if isinstance(value, float):

        if not math.isfinite(value):
            raise ValueError(
                "value cannot be NaN or infinite"
            )

        if value == 0:
            return 0.0

        return value

    if isinstance(value, str):

        value = unicodedata.normalize(
            "NFC",
            value,
        )

        value = value.strip()

        if not value:
            raise ValueError(
                "string value cannot be empty"
            )

        return value

    if isinstance(value, list):
        return [
            canonicalize_value(item)
            for item in value
        ]

    if isinstance(value, dict):

        canonical_value = {}

        for key, item in value.items():

            if not isinstance(key, str):
                raise TypeError(
                    "object keys must be strings"
                )

            canonical_key = (
                unicodedata.normalize(
                    "NFC",
                    key,
                ).strip()
            )

            if not canonical_key:
                raise ValueError(
                    "object keys cannot be empty"
                )

            if canonical_key in canonical_value:
                raise ValueError(
                    "object contains duplicate canonical keys"
                )

            canonical_value[canonical_key] = (
                canonicalize_value(item)
            )

        return canonical_value

    raise TypeError(
        "value must be a supported JSON data type"
    )


def canonicalize_assertion(
    source_kind: str,
    source: str,
    entity_namespace: str,
    entity: str,
    attribute: str,
    value: Any,
) -> dict[str, Any]:
    """
    Converts an assertion into its canonical form.
    """

    return {
        "source_kind": source_kind,
        "source": canonicalize_source(
            source_kind,
            source,
        ),
        "entity_namespace": entity_namespace,
        "entity": canonicalize_entity(
            entity_namespace,
            entity,
        ),
        "attribute": canonicalize_attribute(
            attribute,
        ),
        "value": canonicalize_value(
            value,
        ),
    }