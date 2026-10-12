"""Explicit dependency boundary for asymmetric OAuth and account authentication."""
from importlib.metadata import PackageNotFoundError, version

from packaging.version import InvalidVersion, Version


class CryptoDependencyError(RuntimeError):
    """The requested authentication capability lacks its secure backend."""


def require_crypto():
    message = ("Asymmetric OAuth/account authentication requires PyJWT>=2.15.0 and "
               "cryptography>=50.0.1. Install 'omneum[oauth]' on a platform with "
               "supported public crypto wheels (macOS arm64 or Linux x86_64).")
    try:
        if Version(version("PyJWT")) < Version("2.15.0") or Version(version("cryptography")) < Version("50.0.1"):
            raise CryptoDependencyError(message)
        import jwt
        if not jwt.algorithms.has_crypto:
            raise CryptoDependencyError(message)
    except (PackageNotFoundError, InvalidVersion, ImportError) as error:
        raise CryptoDependencyError(message) from error
