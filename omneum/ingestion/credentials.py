"""One credential authority for HTTP admission and ingestion; no token logging."""
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
import re
import secrets
from uuid import UUID, uuid4

from ..base64url import decode_unpadded, encode_unpadded

_TOKEN = re.compile(r'omn1_([0-9a-f]{32})_([A-Za-z0-9_-]{43})')
_DOMAIN = b'OMNEUM-NETWORK-CREDENTIAL-V1\x00'


def digest(token):
    return sha256(_DOMAIN + token.encode('ascii')).digest()


@dataclass(frozen=True, slots=True)
class IssuedCredential:
    id: UUID
    token: str = field(repr=False)
    token_sha256: bytes = field(repr=False)
    expires_at: datetime


def generate(expires_at):
    identifier = uuid4()
    # 256 bits of independent random secret material; these are not passwords.
    token = f'omn1_{identifier.hex}_{encode_unpadded(secrets.token_bytes(32), expected_length=32)}'
    return IssuedCredential(identifier, token, digest(token), expires_at)


class CredentialAuthenticator:
    def __init__(self, connection_factory):
        self._connections = connection_factory

    def authenticate(self, credential: str, /) -> UUID | None:
        if type(credential) is not str:
            return None
        match = _TOKEN.fullmatch(credential)
        if match is None:
            return None
        try:
            # Reject alternate/noncanonical encodings before accessing storage.
            decode_unpadded(match[2], expected_length=32)
            with self._connections() as db:
                db.execute("SET statement_timeout = '5s'")
                row = db.execute("""
                    SELECT p.principal_id, c.token_sha256
                    FROM control.ingestion_credentials c
                    JOIN control.ingestion_principals p ON p.principal_id = c.principal_id
                    JOIN control.workspaces w ON w.id = p.workspace_id
                    WHERE c.id = %s AND c.revoked_at IS NULL
                      AND c.expires_at > clock_timestamp() AND p.enabled
                      AND EXISTS (SELECT 1 FROM control.consent_grants g
                        WHERE g.installation_id = p.installation_id
                          AND g.scope = 'research_context_graph' AND g.revoked_at IS NULL)
                """, (UUID(hex=match[1]),)).fetchone()
            if row and secrets.compare_digest(bytes(row[1]), digest(credential)):
                return row[0]
        except Exception:
            # Database outages and malformed credentials deny admission safely.
            pass
        return None
