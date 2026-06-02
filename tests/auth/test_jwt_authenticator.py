"""Tests for JWTAuthenticator."""

import time

import jwt as pyjwt

from apcore_a2a.auth.jwt import ClaimMapping, JWTAuthenticator
from apcore_a2a.auth.protocol import Authenticator

SECRET = "test-secret-key-that-is-at-least-32-bytes-long"


def make_token(payload: dict, secret: str = SECRET, algorithm: str = "HS256") -> str:
    return pyjwt.encode(payload, secret, algorithm=algorithm)


def headers(token: str) -> dict:
    return {"authorization": f"Bearer {token}"}


# Basic auth
def test_valid_token_returns_identity():
    auth = JWTAuthenticator(SECRET)
    token = make_token({"sub": "user1"})
    identity = auth.authenticate(headers(token))
    assert identity is not None
    assert identity.id == "user1"


def test_missing_header_returns_none():
    auth = JWTAuthenticator(SECRET)
    assert auth.authenticate({}) is None


def test_non_bearer_returns_none():
    auth = JWTAuthenticator(SECRET)
    assert auth.authenticate({"authorization": "Basic dXNlcjpwYXNz"}) is None


def test_invalid_token_returns_none():
    auth = JWTAuthenticator(SECRET)
    assert auth.authenticate({"authorization": "Bearer not.a.token"}) is None


def test_wrong_key_returns_none():
    auth = JWTAuthenticator("different-secret-that-is-at-least-32-bytes")
    token = make_token({"sub": "user1"})
    assert auth.authenticate(headers(token)) is None


def test_expired_token_returns_none():
    auth = JWTAuthenticator(SECRET)
    token = make_token({"sub": "user1", "exp": int(time.time()) - 100})
    assert auth.authenticate(headers(token)) is None


def test_wrong_issuer_returns_none():
    auth = JWTAuthenticator(SECRET, issuer="expected-issuer")
    token = make_token({"sub": "user1", "iss": "wrong-issuer"})
    assert auth.authenticate(headers(token)) is None


def test_correct_issuer_succeeds():
    auth = JWTAuthenticator(SECRET, issuer="https://auth.example.com")
    token = make_token({"sub": "user1", "iss": "https://auth.example.com"})
    identity = auth.authenticate(headers(token))
    assert identity is not None


def test_wrong_audience_returns_none():
    auth = JWTAuthenticator(SECRET, audience="my-api")
    token = make_token({"sub": "user1", "aud": "other-api"}, algorithm="HS256")
    assert auth.authenticate(headers(token)) is None


def test_correct_audience_succeeds():
    auth = JWTAuthenticator(SECRET, audience="my-api")
    token = make_token({"sub": "user1", "aud": "my-api"})
    identity = auth.authenticate(headers(token))
    assert identity is not None


def test_missing_required_claim_returns_none():
    auth = JWTAuthenticator(SECRET, require_claims=["sub", "custom_required"])
    token = make_token({"sub": "user1"})  # missing custom_required
    assert auth.authenticate(headers(token)) is None


# Identity fields
def test_default_identity_type_is_user():
    auth = JWTAuthenticator(SECRET)
    token = make_token({"sub": "user1"})
    identity = auth.authenticate(headers(token))
    assert identity.type == "user"


def test_custom_type_claim():
    auth = JWTAuthenticator(SECRET)
    token = make_token({"sub": "svc1", "type": "service"})
    identity = auth.authenticate(headers(token))
    assert identity.type == "service"


def test_roles_parsed():
    auth = JWTAuthenticator(SECRET)
    token = make_token({"sub": "user1", "roles": ["admin", "editor"]})
    identity = auth.authenticate(headers(token))
    assert set(identity.roles) == {"admin", "editor"}


def test_roles_default_empty():
    auth = JWTAuthenticator(SECRET)
    token = make_token({"sub": "user1"})
    identity = auth.authenticate(headers(token))
    assert identity.roles == () or list(identity.roles) == []


def test_custom_claim_mapping():
    mapping = ClaimMapping(id_claim="email", type_claim="role", roles_claim="perms")
    auth = JWTAuthenticator(SECRET, claim_mapping=mapping, require_claims=["email"])
    token = make_token({"email": "alice@example.com", "role": "admin", "perms": ["read"]})
    identity = auth.authenticate(headers(token))
    assert identity.id == "alice@example.com"
    assert identity.type == "admin"


def test_attrs_claims():
    mapping = ClaimMapping(attrs_claims=["org", "dept"])
    auth = JWTAuthenticator(SECRET, claim_mapping=mapping)
    token = make_token({"sub": "user1", "org": "acme", "dept": "eng"})
    identity = auth.authenticate(headers(token))
    assert identity.attrs.get("org") == "acme"
    assert identity.attrs.get("dept") == "eng"


# security_schemes
def test_security_schemes_returns_dict():
    """security_schemes() must return a dict keyed by scheme name (AgentCard-compatible)."""
    auth = JWTAuthenticator(SECRET)
    schemes = auth.security_schemes()
    assert isinstance(schemes, dict)
    assert "bearerAuth" in schemes
    assert schemes["bearerAuth"]["type"] == "http"
    assert schemes["bearerAuth"]["scheme"] == "bearer"
    assert schemes["bearerAuth"]["bearerFormat"] == "JWT"


def test_security_schemes_compatible_with_agent_card():
    """T2: JWTAuthenticator.security_schemes() output can be passed to AgentCardBuilder.build()."""
    from unittest.mock import MagicMock

    from a2a.types import AgentCapabilities

    from apcore_a2a.adapters.agent_card import AgentCardBuilder
    from apcore_a2a.adapters.skill_mapper import SkillMapper

    auth = JWTAuthenticator(SECRET)
    schemes = auth.security_schemes()

    registry = MagicMock()
    registry.list.return_value = []

    builder = AgentCardBuilder(SkillMapper())
    # This must not raise — confirms the dict format is accepted by AgentCard
    card = builder.build(
        registry,
        name="Agent",
        description="Test",
        version="1.0",
        url="http://localhost",
        capabilities=AgentCapabilities(streaming=False, push_notifications=False),
        security_schemes=schemes,
    )
    # In a2a-sdk 1.0, security_schemes is a proto map — non-empty when set
    assert "bearerAuth" in card.security_schemes


# Protocol
def test_protocol_compliance():
    auth = JWTAuthenticator(SECRET)
    assert isinstance(auth, Authenticator)


# Claim coercion — canonical cross-language rule (strict, Rust-aligned)
def test_non_scalar_sub_claim_is_rejected():
    # A-D-101: a list/dict `sub` is not a valid identity id; reject the token
    # rather than coercing it to "[1, 2]" / "{...}".
    auth = JWTAuthenticator(SECRET)
    assert auth.authenticate(headers(make_token({"sub": [1, 2]}))) is None
    assert auth.authenticate(headers(make_token({"sub": {"a": 1}}))) is None


def test_numeric_sub_claim_is_coerced_to_string():
    auth = JWTAuthenticator(SECRET)
    identity = auth.authenticate(headers(make_token({"sub": 12345})))
    assert identity is not None
    assert identity.id == "12345"


def test_bool_claim_is_lowercase_stringified():
    # A scalar bool coerces to lowercase "true"/"false" (parity with Rust/TS).
    auth = JWTAuthenticator(SECRET)
    identity = auth.authenticate(headers(make_token({"sub": True})))
    assert identity is not None
    assert identity.id == "true"


def test_null_type_claim_falls_back_to_user():
    # A-D-102: an explicit null type must fall back to "user", not "None".
    auth = JWTAuthenticator(SECRET)
    identity = auth.authenticate(headers(make_token({"sub": "u", "type": None})))
    assert identity is not None
    assert identity.type == "user"


def test_numeric_type_claim_is_coerced():
    auth = JWTAuthenticator(SECRET)
    identity = auth.authenticate(headers(make_token({"sub": "u", "type": 5})))
    assert identity is not None
    assert identity.type == "5"


def test_empty_string_type_claim_is_preserved():
    # Only absent/null/non-scalar falls back to "user"; "" is a valid scalar.
    auth = JWTAuthenticator(SECRET)
    identity = auth.authenticate(headers(make_token({"sub": "u", "type": ""})))
    assert identity is not None
    assert identity.type == ""


def test_non_scalar_role_elements_are_dropped():
    # A-D-103: null/array/object role elements are dropped; scalars are coerced.
    auth = JWTAuthenticator(SECRET)
    identity = auth.authenticate(headers(make_token({"sub": "u", "roles": ["admin", 7, None, ["x"], {"k": 1}]})))
    assert identity is not None
    assert tuple(identity.roles) == ("admin", "7")
