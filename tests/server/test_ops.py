"""Tests for ops endpoints (Health/Metrics/Dynamic Registration) — factory-based."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient

from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from apcore_a2a.server.factory import A2AServerFactory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_registry(module_ids=None):
    reg = MagicMock()
    reg.list.return_value = module_ids or []
    reg.get_definition.return_value = None
    return reg


def make_executor():
    ex = MagicMock()
    ex.call_async = AsyncMock(return_value={"result": "ok"})
    return ex


def make_app(registry=None, metrics=False, task_store=None):
    factory = A2AServerFactory()
    reg = registry or make_registry()
    kwargs: dict = dict(name="test", description="d", version="1", url="http://x", metrics=metrics)
    if task_store is not None:
        kwargs["task_store"] = task_store
    app, _ = factory.create(reg, make_executor(), **kwargs)
    return app, factory


# ---------------------------------------------------------------------------
# Sub-feature 1: Health endpoint
# ---------------------------------------------------------------------------


def test_health_returns_200():
    app, _ = make_app()
    resp = TestClient(app).get("/health")
    assert resp.status_code == 200


def test_health_includes_uptime():
    app, _ = make_app()
    data = TestClient(app).get("/health").json()
    assert "uptime_seconds" in data
    assert data["uptime_seconds"] >= 0


def test_health_includes_version():
    app, _ = make_app()
    data = TestClient(app).get("/health").json()
    assert data["version"] == "1"


def test_health_includes_module_count():
    reg = make_registry(module_ids=["mod.a", "mod.b", "mod.c"])
    app, _ = make_app(registry=reg)
    data = TestClient(app).get("/health").json()
    assert data["module_count"] == 3


def test_health_module_count_zero_when_no_modules():
    reg = make_registry(module_ids=[])
    app, _ = make_app(registry=reg)
    data = TestClient(app).get("/health").json()
    assert data["module_count"] == 0


def test_health_unhealthy_503():
    """When task store's get() raises, health returns 503."""

    class BrokenStore:
        async def get(self, task_id):
            raise ConnectionError("DB is down")

        async def save(self, task):
            pass

        async def delete(self, task_id):
            pass

    app, _ = make_app(task_store=BrokenStore())
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/health")
    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "unhealthy"
    assert "Task store unavailable" in data["reason"]


def test_health_exempt_paths_in_factory_source():
    """The factory source references /health and exempt_paths."""
    import inspect
    import apcore_a2a.server.factory as factory_module

    source = inspect.getsource(factory_module)
    assert '"/health"' in source or "'/health'" in source
    assert "exempt_paths" in source


# ---------------------------------------------------------------------------
# Sub-feature 2: Metrics endpoint
# ---------------------------------------------------------------------------


def test_metrics_disabled_returns_404():
    app, _ = make_app(metrics=False)
    resp = TestClient(app).get("/metrics")
    assert resp.status_code in (404, 405)


def test_metrics_enabled_returns_200():
    app, _ = make_app(metrics=True)
    resp = TestClient(app).get("/metrics")
    assert resp.status_code == 200


def test_metrics_has_expected_fields():
    app, _ = make_app(metrics=True)
    data = TestClient(app).get("/metrics").json()
    for field in ("active_tasks", "completed_tasks", "failed_tasks",
                  "canceled_tasks", "input_required_tasks", "total_requests", "uptime_seconds"):
        assert field in data, f"Missing field: {field}"


def test_metrics_counters_start_at_zero():
    app, _ = make_app(metrics=True)
    data = TestClient(app).get("/metrics").json()
    assert data["active_tasks"] == 0
    assert data["completed_tasks"] == 0
    assert data["failed_tasks"] == 0
    assert data["canceled_tasks"] == 0
    assert data["input_required_tasks"] == 0
    assert data["total_requests"] == 0


def test_metrics_requests_counter():
    """Each POST to / increments total_requests."""
    app, _ = make_app(metrics=True)
    client = TestClient(app)
    for i in range(3):
        body = json.dumps({
            "jsonrpc": "2.0", "id": f"req-{i}",
            "method": "tasks/list", "params": {},
        })
        client.post("/", content=body, headers={"Content-Type": "application/json"})

    data = client.get("/metrics").json()
    assert data["total_requests"] == 3


# ---------------------------------------------------------------------------
# Sub-feature 3: Dynamic registration
# ---------------------------------------------------------------------------


def _make_descriptor(module_id="new.module"):
    desc = MagicMock()
    desc.module_id = module_id
    desc.description = "A new module"
    return desc


def test_register_module_calls_registry_register():
    """register_module() calls registry.register() with the descriptor."""
    factory = A2AServerFactory()
    reg = make_registry()
    factory.create(reg, make_executor(), name="Agent", description="d", version="1", url="http://x")
    desc = _make_descriptor("new.module")
    factory.register_module("new.module", desc)
    reg.register.assert_called_once_with("new.module", desc)


def test_register_module_invalidates_cache():
    """register_module() invalidates the cached card."""
    factory = A2AServerFactory()
    reg = make_registry()
    factory.create(reg, make_executor(), name="Agent", description="d", version="1", url="http://x")
    factory._agent_card_builder._cached_card = MagicMock()  # inject stale
    factory.register_module("mod.x", _make_descriptor())
    assert factory._agent_card_builder._cached_card is None


def test_register_module_logs_info(caplog):
    import logging
    factory = A2AServerFactory()
    reg = make_registry()
    factory.create(reg, make_executor(), name="Agent", description="d", version="1", url="http://x")
    with caplog.at_level(logging.INFO, logger="apcore_a2a.server.factory"):
        factory.register_module("log.test", _make_descriptor("log.test"))
    assert any("log.test" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Factory route checks
# ---------------------------------------------------------------------------


def test_factory_metrics_route_when_enabled():
    app, _ = make_app(metrics=True)
    resp = TestClient(app).get("/metrics")
    assert resp.status_code == 200


def test_factory_no_metrics_route_when_disabled():
    app, _ = make_app(metrics=False)
    resp = TestClient(app).get("/metrics")
    assert resp.status_code in (404, 405)
