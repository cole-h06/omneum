from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from omneum.canonicalization import (
    canonicalize_attribute,
    canonicalize_entity,
    canonicalize_source,
    canonicalize_value,
)
from omneum.linkage import LinkageBlindResult, LinkageClient
from omneum.oprf import VOPRFClient, VOPRFEvaluation


@dataclass(frozen=True, slots=True)
class NetworkLinkageConfig:
    key_version: int
    public_key: bytes

    def __post_init__(self) -> None:
        if (
            type(self.key_version) is not int
            or not 1 <= self.key_version <= 2**32 - 1
        ):
            raise ValueError("network VOPRF key version is invalid")

        if type(self.public_key) is not bytes or len(self.public_key) != 32:
            raise ValueError("network VOPRF public key must be 32 bytes")


@dataclass(frozen=True, slots=True)
class NetworkLinkageToken:
    key_version: int
    value: bytes

    def __post_init__(self) -> None:
        if (
            type(self.key_version) is not int
            or not 1 <= self.key_version <= 2**32 - 1
        ):
            raise ValueError("network VOPRF key version is invalid")

        if type(self.value) is not bytes or len(self.value) != 64:
            raise ValueError("network linkage token must be 64 bytes")


class NetworkLinkageClient:
    def __init__(self, config: NetworkLinkageConfig) -> None:
        if type(config) is not NetworkLinkageConfig:
            raise TypeError(
                "config must be a NetworkLinkageConfig"
            )

        self._config = config
        self._linkage = LinkageClient(
            VOPRFClient(config.public_key)
        )

    @property
    def key_version(self) -> int:
        return self._config.key_version

    def blind_source(
        self,
        kind: str,
        identifier: str,
    ) -> LinkageBlindResult:
        canonical = canonicalize_source(kind, identifier)
        return self._linkage.blind_source(kind, canonical)

    def blind_claim(
        self,
        entity_namespace: str,
        entity: str,
        attribute: str,
        value: Any,
    ) -> LinkageBlindResult:
        canonical_entity = canonicalize_entity(
            entity_namespace,
            entity,
        )
        canonical_attribute = canonicalize_attribute(attribute)
        canonical_value = canonicalize_value(value)

        return self._linkage.blind_claim(
            entity_namespace,
            canonical_entity,
            canonical_attribute,
            canonical_value,
        )

    def finalize(
        self,
        blind: LinkageBlindResult,
        evaluation: VOPRFEvaluation,
    ) -> NetworkLinkageToken:
        return NetworkLinkageToken(
            key_version=self._config.key_version,
            value=self._linkage.finalize(
                blind,
                evaluation,
            ),
        )
