"""Tests for public API: serve() and async_serve() — Feature F-08.

TDD RED → GREEN cycle.
asyncio_mode = "auto" is set in pyproject.toml so all async tests run natively.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from starlette.applications import Starlette
from starlette.testclient import TestClient

# ---------------------------------------------------------------------------
# Minimal ModuleDescriptor stub (mirrors conftest.py)
# ---------------------------------------------------------------------------


@dataclass
class _ModuleDescriptor:
    module_id: str = "test.module"
    description: str = "Test module"
    input_schema: dict | None = None
    output_schema: dict | None = None
    name: str | None = None
    tags: list[str] = field(default_factory=list)
    annotations: Any = None
    examples: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_descriptor(module_id: str = "test.module") -> _ModuleDescriptor:
    return _ModuleDescriptor(
        module_id=module_id,
        description=f"Test module {module_id}",
        input_schema={"type": "object", "properties": {}},
        output_schema={"type": "object", "properties": {}},
    )


def make_mock_registry(modules=None, config=None):
    """Build a mock registry that behaves like an apcore Registry.

    Uses spec to restrict available attributes so duck-typing works correctly
    (a registry should NOT expose call_async).

    modules: dict mapping module_id -> descriptor; if None, defaults to one
             pre-built _ModuleDescriptor so agent card serialisation works.
    """
    if modules is None:
        modules = {"test.module": _make_descriptor("test.module")}

    # Use spec to prevent MagicMock from auto-creating call_async
    class _RegistrySpec:
        def list(self): ...
        def get_definition(self, module_id): ...

        config: dict

    registry = MagicMock(spec=_RegistrySpec)
    registry.list.return_value = list(modules.keys())
    registry.get_definition.side_effect = lambda k: modules.get(k, _make_descriptor(k))
    registry.config = config if config is not None else {}
    return registry


def make_mock_executor(registry=None):
    """Build a mock executor that behaves like an apcore Executor."""
    if registry is None:
        registry = make_mock_registry()

    # Use spec to control exposed attributes
    class _ExecutorSpec:
        async def call_async(self, *args, **kwargs): ...

        registry: Any

    executor = MagicMock(spec=_ExecutorSpec)
    executor.registry = registry
    executor.call_async = AsyncMock(return_value={"result": "ok"})
    return executor


def make_valid_auth():
    """Build a mock auth object that satisfies the Authenticator protocol."""
    auth = MagicMock()
    auth.authenticate = AsyncMock(return_value={"sub": "user"})
    auth.security_schemes.return_value = {}
    return auth


# ---------------------------------------------------------------------------
# async_serve tests
# ---------------------------------------------------------------------------


async def test_async_serve_returns_starlette():
    """Valid registry → async_serve returns a Starlette ASGI instance."""
    from apcore_a2a import async_serve

    registry = make_mock_registry()
    app = await async_serve(registry)
    assert isinstance(app, Starlette)


async def test_async_serve_zero_modules_raises_value_error():
    """Empty registry → ValueError with helpful message."""
    from apcore_a2a import async_serve

    registry = make_mock_registry(modules={})
    with pytest.raises(ValueError, match="zero modules"):
        await async_serve(registry)


async def test_async_serve_invalid_registry_type_raises_type_error():
    """Passing a plain dict (no list/call_async) → TypeError."""
    from apcore_a2a import async_serve

    with pytest.raises(TypeError, match="Expected apcore Registry"):
        await async_serve({"key": "value"})


async def test_async_serve_invalid_auth_raises_type_error():
    """auth object missing authenticate → TypeError."""
    from apcore_a2a import async_serve

    registry = make_mock_registry()
    bad_auth = MagicMock(spec=[])  # no attributes at all
    with pytest.raises(TypeError, match="auth missing required methods"):
        await async_serve(registry, auth=bad_auth)


async def test_async_serve_invalid_task_store_raises_type_error():
    """task_store object missing save → TypeError."""
    from apcore_a2a import async_serve

    registry = make_mock_registry()
    bad_store = MagicMock(spec=[])  # no attributes at all
    with pytest.raises(TypeError, match="task_store missing required methods"):
        await async_serve(registry, task_store=bad_store)


async def test_async_serve_default_task_store_is_in_memory():
    """task_store defaults to InMemoryTaskStore when not provided."""
    from apcore_a2a import async_serve
    from apcore_a2a.server.factory import A2AServerFactory

    registry = make_mock_registry()

    created_store = None

    original_create = A2AServerFactory.create

    def patched_create(self, reg, exc, *, task_store, **kwargs):
        nonlocal created_store
        created_store = task_store
        return original_create(self, reg, exc, task_store=task_store, **kwargs)

    import apcore_a2a._serve as serve_module

    original_factory_class = serve_module.A2AServerFactory

    class CapturingFactory(A2AServerFactory):
        def create(self, reg, exc, *, task_store, **kwargs):
            nonlocal created_store
            created_store = task_store
            return super().create(reg, exc, task_store=task_store, **kwargs)

    serve_module.A2AServerFactory = CapturingFactory  # type: ignore[attr-defined]
    try:
        await async_serve(registry)
    finally:
        serve_module.A2AServerFactory = original_factory_class  # type: ignore[attr-defined]

    assert isinstance(created_store, InMemoryTaskStore)


async def test_async_serve_name_resolution_kwarg():
    """name kwarg takes priority over registry config."""
    from starlette.testclient import TestClient

    from apcore_a2a import async_serve

    config = {"project": {"name": "registry-name", "version": "2.0.0"}}
    registry = make_mock_registry(config=config)

    app = await async_serve(registry, name="kwarg-name")
    client = TestClient(app)
    resp = client.get("/.well-known/agent.json")
    assert resp.status_code == 200
    card = resp.json()
    assert card["name"] == "kwarg-name"


async def test_async_serve_name_resolution_registry_config():
    """name falls back to registry.config['project']['name']."""
    from starlette.testclient import TestClient

    from apcore_a2a import async_serve

    config = {"project": {"name": "config-agent", "version": "3.0.0"}}
    registry = make_mock_registry(config=config)

    app = await async_serve(registry)
    client = TestClient(app)
    resp = client.get("/.well-known/agent.json")
    assert resp.status_code == 200
    card = resp.json()
    assert card["name"] == "config-agent"


async def test_async_serve_name_resolution_fallback():
    """No kwarg, no registry config → name defaults to 'Apcore Agent'."""
    from starlette.testclient import TestClient

    from apcore_a2a import async_serve

    registry = make_mock_registry(config={})
    app = await async_serve(registry)
    client = TestClient(app)
    resp = client.get("/.well-known/agent.json")
    assert resp.status_code == 200
    card = resp.json()
    assert card["name"] == "Apcore Agent"


async def test_async_serve_version_fallback():
    """No kwarg, no registry config → version defaults to '0.0.0'."""
    from starlette.testclient import TestClient

    from apcore_a2a import async_serve

    registry = make_mock_registry(config={})
    app = await async_serve(registry)
    client = TestClient(app)
    resp = client.get("/.well-known/agent.json")
    assert resp.status_code == 200
    card = resp.json()
    assert card["version"] == "0.0.0"


async def test_async_serve_description_fallback():
    """No kwarg, no registry config → description includes 'skills'."""
    from starlette.testclient import TestClient

    from apcore_a2a import async_serve

    registry = make_mock_registry(config={})
    app = await async_serve(registry)
    client = TestClient(app)
    resp = client.get("/.well-known/agent.json")
    assert resp.status_code == 200
    card = resp.json()
    assert "skill" in card["description"].lower()


async def test_async_serve_url_default():
    """url defaults to 'http://localhost:8000' when not provided."""
    from starlette.testclient import TestClient

    from apcore_a2a import async_serve

    registry = make_mock_registry()
    app = await async_serve(registry)
    client = TestClient(app)
    resp = client.get("/.well-known/agent.json")
    assert resp.status_code == 200
    card = resp.json()
    assert card["url"] == "http://localhost:8000"


async def test_async_serve_url_kwarg():
    """Custom url kwarg is used in agent card."""
    from starlette.testclient import TestClient

    from apcore_a2a import async_serve

    registry = make_mock_registry()
    app = await async_serve(registry, url="https://myagent.example.com")
    client = TestClient(app)
    resp = client.get("/.well-known/agent.json")
    assert resp.status_code == 200
    card = resp.json()
    assert card["url"] == "https://myagent.example.com"


async def test_async_serve_with_auth():
    """Valid auth object → no error, app returns."""
    from apcore_a2a import async_serve

    registry = make_mock_registry()
    auth = make_valid_auth()
    app = await async_serve(registry, auth=auth)
    assert isinstance(app, Starlette)


async def test_async_serve_with_custom_task_store():
    """Providing InMemoryTaskStore() explicitly → no error."""
    from apcore_a2a import async_serve

    registry = make_mock_registry()
    store = InMemoryTaskStore()
    app = await async_serve(registry, task_store=store)
    assert isinstance(app, Starlette)


async def test_async_serve_starlette_app_has_routes():
    """Returned Starlette app has /.well-known/agent.json route."""
    from apcore_a2a import async_serve

    registry = make_mock_registry()
    app = await async_serve(registry)
    client = TestClient(app)
    resp = client.get("/.well-known/agent.json")
    assert resp.status_code == 200


async def test_async_serve_starlette_app_has_health_route():
    """Returned Starlette app has /health route."""
    from apcore_a2a import async_serve

    registry = make_mock_registry()
    app = await async_serve(registry)
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200


async def test_async_serve_with_executor():
    """Passing an executor (has call_async) → resolves registry from executor.registry."""
    from apcore_a2a import async_serve

    executor = make_mock_executor()
    app = await async_serve(executor)
    assert isinstance(app, Starlette)


async def test_async_serve_push_notifications_flag():
    """push_notifications=True passes through to factory without error."""
    from apcore_a2a import async_serve

    registry = make_mock_registry()
    app = await async_serve(registry, push_notifications=True)
    assert isinstance(app, Starlette)


async def test_async_serve_cors_origins():
    """cors_origins list passes through without error."""
    from apcore_a2a import async_serve

    registry = make_mock_registry()
    app = await async_serve(registry, cors_origins=["https://example.com"])
    assert isinstance(app, Starlette)


# ---------------------------------------------------------------------------
# Top-level import tests
# ---------------------------------------------------------------------------


def test_a2a_client_importable_from_top_level():
    """from apcore_a2a import A2AClient should work."""
    from apcore_a2a import A2AClient  # noqa: F401 — import-only test

    assert A2AClient is not None


def test_version_exported():
    """apcore_a2a.__version__ is a non-empty string."""
    import apcore_a2a

    assert isinstance(apcore_a2a.__version__, str)
    assert len(apcore_a2a.__version__) > 0


def test_serve_importable_from_top_level():
    """from apcore_a2a import serve should work."""
    from apcore_a2a import serve  # noqa: F401

    assert callable(serve)


def test_async_serve_importable_from_top_level():
    """from apcore_a2a import async_serve should work."""
    from apcore_a2a import async_serve  # noqa: F401

    assert callable(async_serve)


# ---------------------------------------------------------------------------
# Path string shortcut tests
# ---------------------------------------------------------------------------


async def test_async_serve_with_path_string(tmp_path):
    """Passing a path string auto-discovers modules and returns Starlette app."""
    from apcore_a2a import async_serve

    # Create a minimal class-based module in the extensions dir
    ext_dir = tmp_path / "extensions"
    ext_dir.mkdir()
    (ext_dir / "echo.py").write_text(
        "from pydantic import BaseModel\n"
        "\n"
        "class EchoInput(BaseModel):\n"
        '    text: str = ""\n'
        "\n"
        "class EchoOutput(BaseModel):\n"
        '    text: str = ""\n'
        "\n"
        "class Echo:\n"
        "    input_schema = EchoInput\n"
        "    output_schema = EchoOutput\n"
        '    description = "Echo module"\n'
        "\n"
        "    def execute(self, inputs, ctx=None):\n"
        '        return {"text": inputs.get("text", "")}\n'
    )

    app = await async_serve(str(ext_dir))
    assert isinstance(app, Starlette)

    # Verify the discovered module appears in the agent card
    client = TestClient(app)
    resp = client.get("/.well-known/agent.json")
    assert resp.status_code == 200
    card = resp.json()
    skill_ids = [s["id"] for s in card.get("skills", [])]
    assert "echo" in skill_ids


async def test_async_serve_with_pathlib_path(tmp_path):
    """Passing a pathlib.Path works the same as a string path."""
    from pathlib import Path

    from apcore_a2a import async_serve

    ext_dir = tmp_path / "extensions"
    ext_dir.mkdir()
    (ext_dir / "ping.py").write_text(
        "from pydantic import BaseModel\n"
        "\n"
        "class PingInput(BaseModel):\n"
        "    pass\n"
        "\n"
        "class PingOutput(BaseModel):\n"
        "    pong: bool = True\n"
        "\n"
        "class Ping:\n"
        "    input_schema = PingInput\n"
        "    output_schema = PingOutput\n"
        '    description = "Ping module"\n'
        "\n"
        "    def execute(self, inputs, ctx=None):\n"
        '        return {"pong": True}\n'
    )

    app = await async_serve(Path(ext_dir))
    assert isinstance(app, Starlette)


async def test_async_serve_with_empty_path_raises_value_error(tmp_path):
    """Path with no modules → ValueError (zero modules)."""
    from apcore_a2a import async_serve

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    with pytest.raises(ValueError, match="zero modules"):
        await async_serve(str(empty_dir))
