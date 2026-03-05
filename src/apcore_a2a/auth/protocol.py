"""Authenticator Protocol — pluggable authentication interface."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from apcore import Identity


@runtime_checkable
class Authenticator(Protocol):
    """Protocol for authentication backends.

    Implementations extract credentials from HTTP headers and return
    an ``Identity`` on success, or ``None`` on failure.
    """

    def authenticate(self, headers: dict[str, str]) -> Identity | None:
        """Authenticate a request from its headers.

        Args:
            headers: Lowercase header keys mapped to their values.

        Returns:
            An ``Identity`` if authentication succeeds, ``None`` otherwise.
        """
        ...

    def security_schemes(self) -> dict:
        """Return security scheme descriptors as a dict keyed by scheme name.

        The returned dict is compatible with AgentCard.security_schemes.
        Example: {"bearerAuth": {"type": "http", "scheme": "bearer"}}.
        """
        ...
