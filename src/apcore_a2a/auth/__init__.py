"""Auth: Authenticator Protocol, JWTAuthenticator, AuthMiddleware."""

from apcore_a2a.auth.jwt import ClaimMapping, JWTAuthenticator
from apcore_a2a.auth.middleware import AuthMiddleware, auth_identity_var
from apcore_a2a.auth.protocol import Authenticator

__all__ = [
    "Authenticator",
    "JWTAuthenticator",
    "ClaimMapping",
    "AuthMiddleware",
    "auth_identity_var",
]
