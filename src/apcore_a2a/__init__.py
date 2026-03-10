"""apcore-a2a: Automatic A2A Protocol Adapter for apcore Module Registry."""

from importlib.metadata import PackageNotFoundError, version

from apcore_a2a._serve import async_serve, serve
from apcore_a2a.adapters import AgentCardBuilder, ErrorMapper, PartConverter, SchemaConverter, SkillMapper
from apcore_a2a.auth import Authenticator, AuthMiddleware, ClaimMapping, JWTAuthenticator, auth_identity_var
from apcore_a2a.client import A2AClient
from apcore_a2a.server import A2AServerFactory, ApCoreAgentExecutor

try:
    __version__ = version("apcore-a2a")
except PackageNotFoundError:
    __version__ = "unknown"

__all__ = [
    "serve",
    "async_serve",
    "A2AClient",
    "__version__",
    # Auth
    "Authenticator",
    "JWTAuthenticator",
    "ClaimMapping",
    "AuthMiddleware",
    "auth_identity_var",
    # Adapters
    "AgentCardBuilder",
    "SkillMapper",
    "SchemaConverter",
    "ErrorMapper",
    "PartConverter",
    # Server
    "A2AServerFactory",
    "ApCoreAgentExecutor",
]
