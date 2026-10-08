"""Transport-neutral HTTPS handler core. All dependencies are server-owned."""

from dataclasses import dataclass
from hashlib import sha256
import re
import json
from typing import Callable, ContextManager, Protocol, TYPE_CHECKING
from uuid import UUID

from .validation import MAX_BODY_BYTES, decode
from .postgres import persist, Rejected
from .limits import IngestionLimits

if TYPE_CHECKING:
    from psycopg import Connection


class Authenticator(Protocol):
    def authenticate(self, credential: str, /) -> UUID | None:
        """Verify a bearer/API key server-side; return a stable principal or None.

        Implementations own secret storage, constant-time verification, expiry,
        revocation and scope checks. Never log the credential or request.
        """
        ...


@dataclass(frozen=True, slots=True)
class IngestionResponse:
    status: int
    code: str
    receipt_id: UUID | None = None
    evaluation_run_id: UUID | None = None


class IngestionService:
    def __init__(self, *, authenticator: Authenticator,
                 connection_factory: Callable[[], ContextManager["Connection"]],
                 allowed_key_versions: frozenset[int],
                 limits: IngestionLimits = IngestionLimits()):
        if not allowed_key_versions or any(type(v) is not int or not 1 <= v < 2**32
                                           for v in allowed_key_versions):
            raise ValueError("configure active network key versions")
        if type(limits) is not IngestionLimits:
            raise TypeError("configure server-owned IngestionLimits")
        self._limits = limits
        self._authenticator = authenticator
        self._connections = connection_factory
        self._versions = frozenset(allowed_key_versions)

    def handle(self, *, authorization: str | None, body: bytes) -> IngestionResponse:
        """Accept bounded raw JSON bytes and one Authorization header.

        The HTTPS adapter must limit streaming body/header sizes before buffering,
        reject duplicate Authorization headers, enforce TLS and apply rate limits.
        No request-controlled DB connection, principal, or workspace is accepted.
        """
        if (type(authorization) is not str or len(authorization) > 4096
                or not re.fullmatch(r"(?i:Bearer) [A-Za-z0-9._~+/=-]+", authorization)):
            return IngestionResponse(401, "unauthorized")
        try:
            principal = self._authenticator.authenticate(authorization[7:])
        except Exception:
            return IngestionResponse(401, "unauthorized")
        if type(principal) is not UUID:
            return IngestionResponse(401, "unauthorized")
        if type(body) is not bytes:
            return IngestionResponse(400, "invalid_contribution")
        if len(body) > MAX_BODY_BYTES:
            return IngestionResponse(413, "request_too_large")
        try:
            contribution = decode(body, self._versions)
            fingerprint = sha256(json.dumps(contribution.model_dump(mode="json"),
                                            sort_keys=True, separators=(",", ":"),
                                            allow_nan=False).encode()).digest()
        except Exception:
            return IngestionResponse(400, "invalid_contribution")
        try:
            # One exclusive, idle connection per call; persist commits before reply.
            with self._connections() as connection:
                receipt, run = persist(connection, principal, contribution, fingerprint, self._limits)
            return IngestionResponse(200, "accepted", receipt, run)
        except Rejected as error:
            return IngestionResponse(error.status, error.code)
        except Exception:
            # No exception objects, SQL text, tokens, or payloads leave this boundary.
            return IngestionResponse(503, "ingestion_unavailable")
