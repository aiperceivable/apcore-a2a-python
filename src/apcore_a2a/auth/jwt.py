"""JWT-based authenticator implementation."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import jwt as pyjwt
from apcore import Identity

logger = logging.getLogger(__name__)


def _claim_to_string(value: Any) -> str | None:
    """Coerce a JWT claim value to a string using the canonical cross-language rule.

    Mirrors the Rust SDK's ``claim_to_string`` (the agreed-upon canonical behaviour):
    strings pass through, numbers and booleans are stringified (``True`` -> ``"true"``),
    and ``null`` / arrays / objects are rejected (return ``None``). This keeps the three
    SDKs in agreement on whether a malformed (non-scalar) claim is accepted, and on the
    exact string an accepted claim produces.
    """
    # bool is a subclass of int, so it must be checked first.
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if isinstance(value, int | float):
        return str(value)
    return None


@dataclass(frozen=True)
class ClaimMapping:
    """Maps JWT claims to ``Identity`` fields.

    Attributes:
        id_claim: Claim used as ``Identity.id``.
        type_claim: Claim used as ``Identity.type``.
        roles_claim: Claim used as ``Identity.roles`` (expects a list).
        attrs_claims: Extra claims to copy into ``Identity.attrs``.
    """

    id_claim: str = "sub"
    type_claim: str = "type"
    roles_claim: str = "roles"
    attrs_claims: list[str] = field(default_factory=list)


class JWTAuthenticator:
    """Validates JWT Bearer tokens and returns ``Identity``.

    Args:
        key: Secret key or public key for verification.
        algorithms: Allowed JWT algorithms.
        audience: Expected ``aud`` claim (optional).
        issuer: Expected ``iss`` claim (optional).
        claim_mapping: Maps JWT claims to Identity fields.
        require_claims: Claims that must be present in the token.
    """

    def __init__(
        self,
        key: str,
        *,
        algorithms: list[str] | None = None,
        audience: str | None = None,
        issuer: str | None = None,
        claim_mapping: ClaimMapping | None = None,
        require_claims: list[str] | None = None,
    ) -> None:
        self._key = key
        self._algorithms = algorithms or ["HS256"]
        self._audience = audience
        self._issuer = issuer
        self._claim_mapping = claim_mapping or ClaimMapping()
        self._require_claims: list[str] = require_claims if require_claims is not None else ["sub"]

    def authenticate(self, headers: dict[str, str]) -> Identity | None:
        """Extract Bearer token from headers, decode, and return Identity."""
        auth_header = headers.get("authorization", "")
        if not auth_header.lower().startswith("bearer "):
            return None

        token = auth_header[7:].strip()
        if not token:
            return None

        payload = self._decode_token(token)
        if payload is None:
            return None

        return self._payload_to_identity(payload)

    def security_schemes(self) -> dict:
        """Return security scheme descriptors for this authenticator.

        Returns a dict keyed by scheme name, compatible with AgentCard.security_schemes.
        """
        return {"bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}}

    def _decode_token(self, token: str) -> dict[str, Any] | None:
        """Decode and validate a JWT token. Returns None on any error."""
        try:
            options: dict[str, Any] = {}
            if self._require_claims:
                options["require"] = self._require_claims
            # Disable PyJWT's RFC sub-type enforcement (PyJWT >= 2.10 rejects a
            # non-string `sub`). The canonical cross-language rule coerces a scalar
            # numeric/boolean `sub` to a string in ``_claim_to_string`` and rejects
            # only null/array/object; deferring the check there keeps Python aligned
            # with the Rust/TS SDKs.
            options["verify_sub"] = False

            kwargs: dict[str, Any] = {
                "jwt": token,
                "key": self._key,
                "algorithms": self._algorithms,
                "options": options,
            }
            if self._audience is not None:
                kwargs["audience"] = self._audience
            if self._issuer is not None:
                kwargs["issuer"] = self._issuer

            return pyjwt.decode(**kwargs)
        except pyjwt.InvalidTokenError:
            logger.debug("JWT validation failed", exc_info=True)
            return None
        except Exception:
            logger.warning("Unexpected error during JWT decode", exc_info=True)
            return None

    def _payload_to_identity(self, payload: dict[str, Any]) -> Identity | None:
        """Convert a decoded JWT payload to an Identity.

        Claim coercion follows the canonical cross-language rule (see
        ``_claim_to_string``): the id claim must coerce to a scalar string or the
        token is rejected; a ``null``/non-scalar type claim falls back to ``"user"``;
        and non-scalar role elements are dropped.
        """
        mapping = self._claim_mapping
        identity_id = _claim_to_string(payload.get(mapping.id_claim))
        if identity_id is None:
            return None

        # Only an absent/null/non-scalar type falls back to "user"; an explicit
        # empty-string type is preserved (parity with Rust unwrap_or_else / TS ??).
        identity_type = _claim_to_string(payload.get(mapping.type_claim))
        if identity_type is None:
            identity_type = "user"

        raw_roles = payload.get(mapping.roles_claim)
        roles = (
            tuple(s for r in raw_roles if (s := _claim_to_string(r)) is not None) if isinstance(raw_roles, list) else ()
        )

        attrs: dict[str, Any] = {}
        if mapping.attrs_claims:
            for claim in mapping.attrs_claims:
                if claim in payload:
                    attrs[claim] = payload[claim]

        return Identity(
            id=identity_id,
            type=identity_type,
            roles=roles,
            attrs=attrs,
        )
