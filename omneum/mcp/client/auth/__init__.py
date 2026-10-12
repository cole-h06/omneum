"""
OAuth2 Authentication implementation for HTTPX.

Implements authorization code flow with PKCE and automatic token refresh.
"""

from omneum.mcp.client.auth.exceptions import OAuthFlowError, OAuthRegistrationError, OAuthTokenError
from omneum.mcp.client.auth.oauth2 import (
    OAuthClientProvider,
    PKCEParameters,
    TokenStorage,
)

__all__ = [
    "OAuthClientProvider",
    "OAuthFlowError",
    "OAuthRegistrationError",
    "OAuthTokenError",
    "PKCEParameters",
    "TokenStorage",
]
