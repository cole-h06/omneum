"""The bundled SDK must preserve stdio and fail closed at crypto boundaries."""
import asyncio
import hashlib
from importlib.metadata import PackageNotFoundError
import json
from pathlib import Path
import subprocess
import sys
import tomllib

import pytest

from omneum import _crypto
from omneum.mcp.client.auth.extensions.client_credentials import JWTParameters, SignedJWTParameters


ROOT = Path(__file__).resolve().parents[1]


def test_bundle_provenance_and_dependency_boundary():
    root = ROOT / "omneum/mcp"
    manifest = json.loads((root / "UPSTREAM.json").read_text())
    assert manifest["revision"] == "777b8d06710c140e3606b0d4598e2aa48546c266"
    for name, digest in manifest["files"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest, name
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert not any(req.lower().startswith(("mcp", "cryptography")) for req in project["dependencies"])
    assert "PyJWT[crypto]>=2.15.0,<3" in project["optional-dependencies"]["oauth"]
    assert "cryptography>=50.0.1" in project["optional-dependencies"]["oauth"]


@pytest.mark.parametrize("package,value", [("cryptography", None), ("cryptography", "48.0.1"),
                                           ("PyJWT", "2.13.0")])
def test_authentication_requires_secure_backend(monkeypatch, package, value):
    def version(name):
        if name == package:
            if value is None:
                raise PackageNotFoundError(name)
            return value
        return {"PyJWT": "2.15.0", "cryptography": "50.0.1"}[name]
    monkeypatch.setattr(_crypto, "version", version)
    from omneum.enrollment import OIDCAuthenticator
    with pytest.raises(_crypto.CryptoDependencyError, match="cryptography>=50.0.1"):
        OIDCAuthenticator(issuer="https://account.example.test", audience="account", jwks_path="unused")
    from omneum.network_deploy import validate_jwks
    with pytest.raises(_crypto.CryptoDependencyError):
        validate_jwks({"keys": []})
    signed = SignedJWTParameters(issuer="client", subject="client", signing_key="unused")
    with pytest.raises(_crypto.CryptoDependencyError):
        asyncio.run(signed.create_assertion_provider()("https://account.example.test"))
    with pytest.raises(_crypto.CryptoDependencyError):
        JWTParameters(issuer="client", subject="client", audience="https://account.example.test",
                      jwt_signing_key="unused").to_assertion()


def test_imports_without_official_sdk_or_crypto():
    # Use real imports and PyJWT's real absent-backend path, rather than a JWT stub.
    script = r'''
import importlib.abc
import sys
class Forbidden(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'mcp' or fullname.startswith('mcp.') or fullname == 'cryptography' or fullname.startswith('cryptography.'):
            raise ModuleNotFoundError('optional dependency unavailable', name=fullname)
sys.meta_path.insert(0, Forbidden())
import omneum.server, omneum.contributor, omneum.installation
from omneum.mcp import ClientSession, StdioServerParameters, stdio_client
from omneum.mcp.server.fastmcp import FastMCP
from omneum.mcp.client.auth.extensions.client_credentials import SignedJWTParameters
from omneum._crypto import CryptoDependencyError
import asyncio, jwt
assert not jwt.algorithms.has_crypto
signed = SignedJWTParameters(issuer='client', subject='client', signing_key='unused')
try:
    asyncio.run(signed.create_assertion_provider()('https://account.example.test'))
except CryptoDependencyError:
    pass
else:
    raise AssertionError('asymmetric signing did not fail explicitly')
assert jwt.get_unverified_header(jwt.encode({'sub':'client'}, 'test-only-secret-that-is-at-least-32-bytes', algorithm='HS256'))['alg'] == 'HS256'
'''
    subprocess.run([sys.executable, "-c", script], cwd=ROOT, check=True, timeout=30)


@pytest.mark.parametrize("legacy", [False, True])
def test_asymmetric_oauth_signature_and_claims(legacy):
    jwt = pytest.importorskip("jwt")
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
    from jwt.utils import base64url_decode, base64url_encode
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
    audience = "https://account.example.test"
    if legacy:
        token = JWTParameters(issuer="client", subject="client", audience=audience, jwt_signing_key=pem).to_assertion()
    else:
        token = asyncio.run(SignedJWTParameters(issuer="client", subject="client", signing_key=pem)
                            .create_assertion_provider()(audience))
    assert jwt.get_unverified_header(token)["alg"] == "RS256"
    claims = jwt.decode(token, key.public_key(), algorithms=["RS256"], issuer="client", audience=audience,
                        options={"require": ["iss", "sub", "aud", "exp", "iat", "jti"]})
    assert claims["sub"] == "client" and claims["exp"] - claims["iat"] == 300
    with pytest.raises(jwt.InvalidAudienceError):
        jwt.decode(token, key.public_key(), algorithms=["RS256"], audience="other")
    header, payload, signature = token.split(".")
    corrupted = bytearray(base64url_decode(signature)); corrupted[0] ^= 1
    forged = ".".join((header, payload, base64url_encode(bytes(corrupted)).decode()))
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(forged, key.public_key(), algorithms=["RS256"], audience=audience)
    with pytest.raises(jwt.InvalidAlgorithmError):
        jwt.decode(token, "unused", algorithms=["HS256"])


def test_prebuilt_assertion_is_not_re_signed(monkeypatch):
    def unavailable():
        raise AssertionError("prebuilt assertions must not acquire a signing backend")
    monkeypatch.setattr("omneum.mcp.client.auth.extensions.client_credentials.require_crypto", unavailable)
    assert JWTParameters(assertion="opaque-prebuilt-assertion").to_assertion() == "opaque-prebuilt-assertion"
