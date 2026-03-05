"""apcore-a2a: Automatic A2A Protocol Adapter for apcore Module Registry."""

from importlib.metadata import PackageNotFoundError, version

from apcore_a2a._serve import async_serve, serve
from apcore_a2a.client import A2AClient

try:
    __version__ = version("apcore-a2a")
except PackageNotFoundError:
    __version__ = "unknown"

__all__ = [
    "serve",
    "async_serve",
    "A2AClient",
    "__version__",
]
