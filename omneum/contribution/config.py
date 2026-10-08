"""Explicit network consent and client-only transport boundaries."""
from __future__ import annotations

import asyncio
import json
import math
import re
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import UUID

from .linkage import NetworkLinkageConfig
from .models import EvaluationContribution
from .validation import decode, _object
from ..oprf import VOPRFEvaluation


class NetworkEvaluator(Protocol):
    async def evaluate(self, *, key_version: int, blinded_element: bytes) -> VOPRFEvaluation:
        """Use authenticated network VOPRF service; never receive unblinded inputs."""
        ...


def _validate_credential(token):
    if (type(token) is not str or len(token) > 4089
            or not re.fullmatch(r"[A-Za-z0-9._~+/=-]+", token)):
        raise ValueError("invalid network credential")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


@dataclass(frozen=True, slots=True)
class HTTPSContributionTransport:
    """Caller-configured narrow ingestion endpoint. No redirects, proxies, or SQL."""
    endpoint: str = field(repr=False)
    bearer_token: str = field(repr=False)
    timeout_seconds: float = 10.0

    def __post_init__(self):
        # urlsplit strips controls; reject them before parsing so validation and
        # the actual request cannot disagree about the configured destination.
        if (type(self.endpoint) is not str
                or any(ord(c) <= 32 or ord(c) == 127 for c in self.endpoint)):
            raise ValueError("invalid ingestion endpoint")
        try:
            url = urlsplit(self.endpoint)
            port = url.port
        except ValueError:
            raise ValueError("invalid ingestion endpoint") from None
        if port == 0:
            raise ValueError("invalid ingestion endpoint")
        if (url.scheme != "https" or not url.hostname or url.username is not None
                or url.password is not None or url.query or url.fragment):
            raise ValueError("ingestion requires an HTTPS endpoint without credentials or query")
        _validate_credential(self.bearer_token)
        if (type(self.timeout_seconds) not in (float, int)
                or not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0):
            raise ValueError("invalid ingestion deadline")

    async def submit(self, contribution: EvaluationContribution) -> None:
        # EvaluationContribution is the only wire contract accepted here.
        if type(contribution) is not EvaluationContribution:
            raise TypeError("expected EvaluationContribution")
        try:
            validated = EvaluationContribution.model_validate(contribution)
            body = validated.model_dump_json().encode()
            # Models can be mutated or constructed without validation. Validate
            # the exact bytes that will leave the machine, including nested keys,
            # opaque token encoding, endpoint references, ranges and size limits.
            decode(body)
            await asyncio.to_thread(self._send, body)
        except Exception:
            raise RuntimeError("network ingestion failed; acceptance may be uncertain") from None

    def _send(self, body: bytes) -> None:
        request = Request(self.endpoint, data=body, method="POST", headers={
            "Authorization": "Bearer " + self.bearer_token,
            "Content-Type": "application/json",
        })
        with build_opener(ProxyHandler({}), _NoRedirect()).open(
            request, timeout=self.timeout_seconds,
        ) as response:
            raw = response.read(4097)
            if response.status != 200 or len(raw) > 4096:
                raise ValueError("invalid ingestion response")
            result = json.loads(raw, object_pairs_hook=_object)
            if (set(result) != {"status", "code", "receipt_id", "evaluation_run_id"}
                    or type(result["status"]) is not int or result["status"] != 200
                    or result["code"] != "accepted"):
                raise ValueError("invalid ingestion response")
            for name in ("receipt_id", "evaluation_run_id"):
                value = result[name]
                if type(value) is not str or str(UUID(value)) != value:
                    raise ValueError("invalid ingestion response")


@dataclass(frozen=True, slots=True)
class NetworkContributionConfig:
    """Explicit opt-in to the pseudonymous region of the shared Context Graph.

    All three dependencies are required. The evaluator must use the authenticated
    network VOPRF service and its independently provisioned network key.
    """
    linkage: NetworkLinkageConfig = field(repr=False)
    evaluator: NetworkEvaluator = field(repr=False)
    transport: HTTPSContributionTransport = field(repr=False)

    def __post_init__(self):
        if type(self.linkage) is not NetworkLinkageConfig:
            raise TypeError("linkage must be a NetworkLinkageConfig")
        if not callable(getattr(self.evaluator, "evaluate", None)):
            raise TypeError("evaluator must implement NetworkEvaluator")
        if type(self.transport) is not HTTPSContributionTransport:
            raise TypeError("transport must be an HTTPSContributionTransport")
