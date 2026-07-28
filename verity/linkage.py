from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

from .oprf import OPRFClient
from .serialization import (
    MAX_LINKAGE_PAYLOAD_SIZE,
    serialize_attribute,
    serialize_claim,
    serialize_source,
)


PROTOCOL_LABEL = b"VERITY-OPRF\x00"
ENCODING_VERSION = 1
MAX_LINKAGE_INPUT_SIZE = 65_534
HEADER_SIZE = 17


class LinkagePurpose(IntEnum):
    SOURCE = 0x01
    ATTRIBUTE = 0x02
    CLAIM = 0x03


@dataclass(frozen=True, slots=True)
class LinkageBlindResult:
    blinded_element: bytes
    purpose: LinkagePurpose
    encoding_version: int
    _encoded_input: bytes = field(repr=False)
    _client_state: bytes = field(repr=False)


def encode_linkage_input(
    canonical_payload: bytes,
    purpose: LinkagePurpose,
    encoding_version: int = ENCODING_VERSION,
) -> bytes:
    if type(canonical_payload) is not bytes:
        raise TypeError(
            "canonical_payload must be bytes"
        )

    if type(purpose) is not LinkagePurpose:
        raise TypeError(
            "purpose must be a LinkagePurpose"
        )

    if type(encoding_version) is not int:
        raise TypeError(
            "encoding_version must be an integer"
        )

    if encoding_version != ENCODING_VERSION:
        raise ValueError(
            "unsupported encoding version"
        )

    if not canonical_payload:
        raise ValueError(
            "canonical_payload must not be empty"
        )

    if len(canonical_payload) > MAX_LINKAGE_PAYLOAD_SIZE:
        raise ValueError(
            "canonical_payload is too large"
        )

    encoded = (
        PROTOCOL_LABEL
        + encoding_version.to_bytes(
            2,
            "big",
        )
        + bytes([purpose])
        + len(canonical_payload).to_bytes(
            2,
            "big",
        )
        + canonical_payload
    )

    if len(encoded) > MAX_LINKAGE_INPUT_SIZE:
        raise ValueError(
            "encoded linkage input is too large"
        )

    return encoded


class LinkageClient:
    def __init__(
        self,
        client: OPRFClient | None = None,
    ) -> None:
        self._client = client or OPRFClient()

    def blind_source(
        self,
        kind: str,
        identifier: str,
    ) -> LinkageBlindResult:
        payload = serialize_source(
            kind,
            identifier,
        )
        return self._blind(
            payload,
            LinkagePurpose.SOURCE,
        )

    def blind_attribute(
        self,
        entity_namespace: str,
        entity: str,
        attribute: str,
    ) -> LinkageBlindResult:
        payload = serialize_attribute(
            entity_namespace,
            entity,
            attribute,
        )
        return self._blind(
            payload,
            LinkagePurpose.ATTRIBUTE,
        )

    def blind_claim(
        self,
        entity_namespace: str,
        entity: str,
        attribute: str,
        value: Any,
    ) -> LinkageBlindResult:
        payload = serialize_claim(
            entity_namespace,
            entity,
            attribute,
            value,
        )
        return self._blind(
            payload,
            LinkagePurpose.CLAIM,
        )

    def finalize(
        self,
        result: LinkageBlindResult,
        evaluated_element: bytes,
    ) -> bytes:
        if type(result) is not LinkageBlindResult:
            raise TypeError(
                "result must be a LinkageBlindResult"
            )

        return self._client.finalize(
            input_data=result._encoded_input,
            client_state=result._client_state,
            evaluated_element=evaluated_element,
        )

    def _blind(
        self,
        canonical_payload: bytes,
        purpose: LinkagePurpose,
    ) -> LinkageBlindResult:
        encoded_input = encode_linkage_input(
            canonical_payload,
            purpose,
            ENCODING_VERSION,
        )
        result = self._client.blind(encoded_input)

        return LinkageBlindResult(
            blinded_element=result.blinded_element,
            purpose=purpose,
            encoding_version=ENCODING_VERSION,
            _encoded_input=encoded_input,
            _client_state=result.client_state,
        )
