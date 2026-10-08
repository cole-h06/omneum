"""Pinned Network configuration and authenticated, blinded-only HTTPS evaluation."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
from urllib.request import Request, ProxyHandler, build_opener

from .config import HTTPSContributionTransport, NetworkContributionConfig, _NoRedirect, _validate_credential
from .linkage import NetworkLinkageConfig
from .validation import _object
from ..base64url import decode_unpadded, encode_unpadded
from ..config import PROTOCOL_VERSION, VOPRF_MODE, _validate_deployment_id
from ..linkage import ENCODING_VERSION
from ..models import EvaluateVOPRFRequest, EvaluateVOPRFResponse
from ..oprf import CIPHERSUITE, VOPRFClient, VOPRFEvaluation


@dataclass(frozen=True, slots=True)
class HTTPSNetworkEvaluator:
    endpoint: str = field(repr=False)
    bearer_token: str = field(repr=False)
    deployment_id: str
    key_version: int
    timeout_seconds: float = 10.0

    def __post_init__(self):
        HTTPSContributionTransport(self.endpoint, self.bearer_token, self.timeout_seconds)
        _validate_deployment_id(self.deployment_id)
        if type(self.key_version) is not int or not 1 <= self.key_version < 2**32:
            raise ValueError("invalid network key version")

    async def evaluate(self, *, key_version: int, blinded_element: bytes) -> VOPRFEvaluation:
        try:
            if type(key_version) is not int or key_version != self.key_version:
                raise ValueError("invalid key version")
            if type(blinded_element) is not bytes:
                raise ValueError("invalid blinded element")
            request = EvaluateVOPRFRequest(
                protocol_version=PROTOCOL_VERSION, deployment_id=self.deployment_id,
                voprf_key_version=key_version, voprf_mode=VOPRF_MODE,
                voprf_ciphersuite=CIPHERSUITE, linkage_encoding_version=ENCODING_VERSION,
                blinded_element=encode_unpadded(blinded_element, expected_length=32),
            )
            raw = await asyncio.to_thread(self._send, request.model_dump_json().encode())
            response = EvaluateVOPRFResponse.model_validate(json.loads(raw, object_pairs_hook=_object))
            expected = request.model_dump(exclude={"blinded_element"})
            if response.model_dump(exclude={"evaluated_element", "proof"}) != expected:
                raise ValueError("invalid response metadata")
            return VOPRFEvaluation(
                decode_unpadded(response.evaluated_element, expected_length=32),
                decode_unpadded(response.proof, expected_length=64),
            )
        except Exception:
            raise RuntimeError("network VOPRF evaluation failed") from None

    def _send(self, body: bytes) -> bytes:
        request = Request(self.endpoint, data=body, method="POST", headers={
            "Authorization": "Bearer " + self.bearer_token,
            "Content-Type": "application/json",
        })
        with build_opener(ProxyHandler({}), _NoRedirect()).open(
            request, timeout=self.timeout_seconds,
        ) as response:
            raw = response.read(4097)
            if response.status != 200 or len(raw) > 4096:
                raise ValueError("invalid network VOPRF response")
            return raw


@dataclass(frozen=True, slots=True)
class _ProductionNetwork:
    ingestion_endpoint: str
    voprf_endpoint: str
    deployment_id: str
    key_version: int
    public_key: bytes


# Release-owned pins. Populate only after the production domain and independent
# Network key have been provisioned and verified. Never read these from env,
# local deployment configuration, API responses, or caller arguments.
_PRODUCTION_NETWORK: _ProductionNetwork | None = None


class OmneumNetwork:
    @staticmethod
    def pseudonymous(*, api_key: str) -> NetworkContributionConfig:
        # Validate without echoing secrets, even while provisioning is pending.
        _validate_credential(api_key)
        pins = _PRODUCTION_NETWORK
        if pins is None:
            raise RuntimeError("Omneum Network production configuration is not provisioned")
        VOPRFClient(pins.public_key)
        return NetworkContributionConfig(
            linkage=NetworkLinkageConfig(pins.key_version, pins.public_key),
            evaluator=HTTPSNetworkEvaluator(pins.voprf_endpoint, api_key,
                                            pins.deployment_id, pins.key_version),
            transport=HTTPSContributionTransport(pins.ingestion_endpoint, api_key),
        )
