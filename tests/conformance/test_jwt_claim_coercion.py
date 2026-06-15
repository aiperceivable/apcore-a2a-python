"""Conformance — Algorithm A-AUTH: JWT claim -> Identity coercion parity.

Fixture: ``conformance/fixtures/jwt_claim_coercion.json`` (shared verbatim with
the TypeScript and Rust runners). Signs each payload with the fixture secret,
calls :meth:`JWTAuthenticator.authenticate`, and asserts the derived Identity or
a rejection (``None``).
"""

from __future__ import annotations

import time
from typing import Any

import jwt as pyjwt
import pytest

from apcore_a2a.auth.jwt import JWTAuthenticator

from ._spec import load_fixture

_FIXTURE = load_fixture("jwt_claim_coercion.json")
_SECRET = _FIXTURE["secret"]
_ALG = _FIXTURE.get("algorithm", "HS256")


def _headers_for(case: dict[str, Any]) -> dict[str, str]:
    """Build request headers for a case: an explicit headers map, or a Bearer
    token signed from the case's claims."""
    if "headers" in case:
        return case["headers"]
    claims = dict(case["claims"])
    # exp_offset_seconds is a fixture convenience (no absolute time in fixtures).
    offset = claims.pop("exp_offset_seconds", None)
    if offset is not None:
        claims["exp"] = int(time.time()) + int(offset)
    secret = case.get("sign_with_secret", _SECRET)
    token = pyjwt.encode(claims, secret, algorithm=_ALG)
    return {"authorization": f"Bearer {token}"}


def _authenticate(case: dict[str, Any]):
    return JWTAuthenticator(_SECRET, algorithms=[_ALG]).authenticate(_headers_for(case))


@pytest.mark.parametrize(
    "case",
    _FIXTURE["test_cases"],
    ids=[c["id"] for c in _FIXTURE["test_cases"]],
)
def test_jwt_claim_coercion_accepts(case: dict[str, Any]) -> None:
    identity = _authenticate(case)
    assert identity is not None, f"[{case['id']}] expected an Identity, got None"
    expected = case["expected_identity"]
    assert identity.id == expected["id"], f"[{case['id']}] id"
    assert identity.type == expected["type"], f"[{case['id']}] type"
    assert list(identity.roles) == expected["roles"], f"[{case['id']}] roles: {list(identity.roles)}"


@pytest.mark.parametrize(
    "case",
    _FIXTURE["reject_cases"],
    ids=[c["id"] for c in _FIXTURE["reject_cases"]],
)
def test_jwt_claim_coercion_rejects(case: dict[str, Any]) -> None:
    assert _authenticate(case) is None, f"[{case['id']}] expected rejection (None)"
