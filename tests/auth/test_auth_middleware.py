"""Tests for AuthMiddleware."""
import json
import pytest
from unittest.mock import MagicMock
from apcore_a2a.auth.middleware import AuthMiddleware, auth_identity_var

class FakeIdentity:
    def __init__(self, id="user1"):
        self.id = id

def make_scope(path="/", headers=None):
    raw_headers = []
    for k, v in (headers or {}).items():
        raw_headers.append((k.encode(), v.encode()))
    return {"type": "http", "path": path, "headers": raw_headers}

async def collect_response(middleware, scope):
    """Call middleware and return (status, body)."""
    messages = []
    async def receive(): return {}
    async def send(msg): messages.append(msg)
    await middleware(scope, receive, send)
    status = next((m["status"] for m in messages if m["type"] == "http.response.start"), None)
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return status, body

async def test_valid_auth_sets_identity():
    identity = FakeIdentity("alice")
    authenticator = MagicMock()
    authenticator.authenticate.return_value = identity

    captured = []
    async def app(scope, receive, send):
        captured.append(auth_identity_var.get())

    middleware = AuthMiddleware(app, authenticator)
    scope = make_scope("/api", {"authorization": "Bearer token123"})
    async def receive(): return {}
    async def send(msg): pass
    await middleware(scope, receive, send)
    assert captured[0] is identity

async def test_invalid_auth_require_true_returns_401():
    authenticator = MagicMock()
    authenticator.authenticate.return_value = None
    app = MagicMock()
    middleware = AuthMiddleware(app, authenticator, require_auth=True)
    scope = make_scope("/api")
    status, body = await collect_response(middleware, scope)
    assert status == 401
    data = json.loads(body)
    assert "error" in data
    app.assert_not_called()

async def test_invalid_auth_require_false_proceeds():
    authenticator = MagicMock()
    authenticator.authenticate.return_value = None
    captured = []
    async def app(scope, receive, send):
        captured.append(auth_identity_var.get())

    middleware = AuthMiddleware(app, authenticator, require_auth=False)
    scope = make_scope("/api")
    async def receive(): return {}
    async def send(msg): pass
    await middleware(scope, receive, send)
    assert captured[0] is None

async def test_exempt_path_skips_auth():
    authenticator = MagicMock()
    authenticator.authenticate.return_value = None
    captured_called = []
    async def app(scope, receive, send):
        captured_called.append(True)

    middleware = AuthMiddleware(app, authenticator, require_auth=True,
                                exempt_paths={"/.well-known/agent.json", "/health", "/metrics"})
    scope = make_scope("/.well-known/agent.json")
    async def receive(): return {}
    async def send(msg): pass
    await middleware(scope, receive, send)
    assert captured_called == [True]
    authenticator.authenticate.assert_not_called()

async def test_exempt_prefix_skips_auth():
    authenticator = MagicMock()
    authenticator.authenticate.return_value = None
    captured_called = []
    async def app(scope, receive, send):
        captured_called.append(True)

    middleware = AuthMiddleware(app, authenticator, require_auth=True,
                                exempt_prefixes={"/explorer"})
    scope = make_scope("/explorer/index.html")
    async def receive(): return {}
    async def send(msg): pass
    await middleware(scope, receive, send)
    assert captured_called == [True]

async def test_non_http_scope_passes_through():
    authenticator = MagicMock()
    captured_called = []
    async def app(scope, receive, send):
        captured_called.append(True)

    middleware = AuthMiddleware(app, authenticator)
    scope = {"type": "lifespan"}
    async def receive(): return {}
    async def send(msg): pass
    await middleware(scope, receive, send)
    assert captured_called == [True]
    authenticator.authenticate.assert_not_called()

async def test_contextvar_reset_after_request():
    identity = FakeIdentity("bob")
    authenticator = MagicMock()
    authenticator.authenticate.return_value = identity
    async def app(scope, receive, send): pass
    middleware = AuthMiddleware(app, authenticator)
    scope = make_scope("/api", {"authorization": "Bearer tok"})
    async def receive(): return {}
    async def send(msg): pass
    await middleware(scope, receive, send)
    # After request, ContextVar should be back to default (None)
    assert auth_identity_var.get() is None

async def test_www_authenticate_header_in_401():
    authenticator = MagicMock()
    authenticator.authenticate.return_value = None
    app = MagicMock()
    middleware = AuthMiddleware(app, authenticator, require_auth=True)
    scope = make_scope("/api")
    messages = []
    async def receive(): return {}
    async def send(msg): messages.append(msg)
    await middleware(scope, receive, send)
    start = next(m for m in messages if m["type"] == "http.response.start")
    headers = dict(start["headers"])
    assert b"www-authenticate" in headers
