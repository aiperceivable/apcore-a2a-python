"""Tests for A2AServerFactory."""
import pytest
from unittest.mock import MagicMock, AsyncMock
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from a2a.types import AgentCard
from starlette.applications import Starlette
from starlette.testclient import TestClient
from apcore_a2a.server.factory import A2AServerFactory


@pytest.fixture
def mock_registry(simple_descriptor):
    reg = MagicMock()
    reg.list.return_value = ["image.resize"]
    reg.get_definition.return_value = simple_descriptor
    return reg


@pytest.fixture
def mock_executor(mock_registry):
    executor = MagicMock()
    executor.call_async = AsyncMock(return_value={"result": "ok"})
    executor.registry = mock_registry
    return executor


def test_create_returns_starlette_and_agent_card(mock_registry, mock_executor):
    factory = A2AServerFactory()
    app, card = factory.create(
        mock_registry,
        mock_executor,
        name="Test Agent",
        description="desc",
        version="1.0.0",
        url="http://localhost:8000",
    )
    assert isinstance(app, Starlette)
    assert isinstance(card, AgentCard)
    assert card.name == "Test Agent"


def test_app_has_well_known_route(mock_registry, mock_executor):
    factory = A2AServerFactory()
    app, _ = factory.create(
        mock_registry, mock_executor,
        name="Agent", description="d", version="1", url="http://x",
    )
    client = TestClient(app)
    # SDK serves both old and new agent card paths
    resp = client.get("/.well-known/agent.json")
    assert resp.status_code == 200


def test_app_has_health_route(mock_registry, mock_executor):
    factory = A2AServerFactory()
    app, _ = factory.create(
        mock_registry, mock_executor,
        name="Agent", description="d", version="1", url="http://x",
    )
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200


def test_app_has_jsonrpc_route(mock_registry, mock_executor):
    factory = A2AServerFactory()
    app, _ = factory.create(
        mock_registry, mock_executor,
        name="Agent", description="d", version="1", url="http://x",
    )
    client = TestClient(app)
    import json
    body = json.dumps({"jsonrpc": "2.0", "id": "1", "method": "tasks/list", "params": {}})
    response = client.post("/", content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 200


def test_agent_card_has_skills(mock_registry, mock_executor, simple_descriptor):
    factory = A2AServerFactory()
    _, card = factory.create(
        mock_registry, mock_executor,
        name="Agent", description="d", version="1", url="http://x",
    )
    assert len(card.skills) == 1
    assert card.skills[0].id == "image.resize"


def test_auth_security_schemes_raises_on_failure(mock_registry, mock_executor):
    """Auth failure in security_schemes() raises (not swallowed)."""
    auth = MagicMock()
    auth.security_schemes.side_effect = ValueError("bad key")
    factory = A2AServerFactory()
    with pytest.raises(ValueError, match="bad key"):
        factory.create(
            mock_registry, mock_executor,
            name="Agent", description="d", version="1", url="http://x",
            auth=auth,
        )


def test_push_notifications_enabled(mock_registry, mock_executor):
    """push_notifications=True enables InMemoryPushNotificationConfigStore."""
    factory = A2AServerFactory()
    app, card = factory.create(
        mock_registry, mock_executor,
        name="Agent", description="d", version="1", url="http://x",
        push_notifications=True,
    )
    assert card.capabilities.push_notifications is True


def test_register_module_invalidates_cache(mock_registry, mock_executor):
    """register_module() invalidates the cached card."""
    factory = A2AServerFactory()
    factory.create(
        mock_registry, mock_executor,
        name="Agent", description="d", version="1", url="http://x",
    )
    factory._agent_card_builder._cached_card = MagicMock()  # inject stale marker
    factory.register_module("new.skill", MagicMock())
    assert factory._agent_card_builder._cached_card is None


def test_metrics_route_when_enabled(mock_registry, mock_executor):
    """metrics=True → /metrics returns 200."""
    factory = A2AServerFactory()
    app, _ = factory.create(
        mock_registry, mock_executor,
        name="Agent", description="d", version="1", url="http://x",
        metrics=True,
    )
    client = TestClient(app)
    resp = client.get("/metrics")
    assert resp.status_code == 200


def test_no_metrics_route_when_disabled(mock_registry, mock_executor):
    """metrics=False (default) → /metrics returns 404."""
    factory = A2AServerFactory()
    app, _ = factory.create(
        mock_registry, mock_executor,
        name="Agent", description="d", version="1", url="http://x",
        metrics=False,
    )
    client = TestClient(app)
    resp = client.get("/metrics")
    assert resp.status_code in (404, 405)


def test_create_returns_starlette_when_metrics_enabled(mock_registry, mock_executor):
    """T1: metrics=True → returned app is still a Starlette instance (not a raw ASGI wrapper)."""
    factory = A2AServerFactory()
    app, _ = factory.create(
        mock_registry, mock_executor,
        name="Agent", description="d", version="1", url="http://x",
        metrics=True,
    )
    assert isinstance(app, Starlette)
