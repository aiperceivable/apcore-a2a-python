"""Tests for A2AClient."""
from __future__ import annotations
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from apcore_a2a.client.exceptions import (
    A2AClientError, A2AConnectionError, A2ADiscoveryError,
    TaskNotFoundError, TaskNotCancelableError, A2AServerError
)
from apcore_a2a.client.client import A2AClient

# --- Exception hierarchy ---
def test_exception_hierarchy():
    assert issubclass(A2AConnectionError, A2AClientError)
    assert issubclass(A2ADiscoveryError, A2AClientError)
    assert issubclass(TaskNotFoundError, A2AClientError)
    assert issubclass(TaskNotCancelableError, A2AClientError)
    assert issubclass(A2AServerError, A2AClientError)

# --- URL validation ---
def test_invalid_url_raises_value_error():
    with pytest.raises(ValueError):
        A2AClient("not-a-url")

def test_http_url_valid():
    client = A2AClient("http://localhost:8000")
    assert client._url == "http://localhost:8000"

def test_https_url_valid():
    client = A2AClient("https://agent.example.com")
    assert client._url == "https://agent.example.com"

def test_trailing_slash_stripped():
    client = A2AClient("http://localhost:8000/")
    assert client._url == "http://localhost:8000"

def test_ftp_url_raises_value_error():
    with pytest.raises(ValueError):
        A2AClient("ftp://example.com")

# --- send_message ---
@pytest.fixture
def mock_http():
    """Mock httpx.AsyncClient."""
    http = MagicMock()
    return http

@pytest.fixture
def task_dict():
    return {
        "id": "task-1",
        "contextId": "ctx-1",
        "status": {"state": "completed", "timestamp": "2026-03-03T10:00:00Z"},
        "artifacts": [],
        "history": [],
        "kind": "task",
    }

async def test_send_message_success(task_dict):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"jsonrpc": "2.0", "id": "1", "result": task_dict}
    response.raise_for_status = MagicMock()

    import httpx
    with patch("httpx.AsyncClient") as mock_cls:
        mock_inst = AsyncMock()
        mock_inst.post = AsyncMock(return_value=response)
        mock_cls.return_value = mock_inst

        client = A2AClient("http://localhost:8000")
        result = await client.send_message(
            {"role": "user", "parts": [{"kind": "text", "text": "hello"}]},
            metadata={"skillId": "image.resize"},
        )
        assert result == task_dict

async def test_send_message_rpc_error_task_not_found():
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"jsonrpc": "2.0", "id": "1", "error": {"code": -32001, "message": "Task not found"}}
    response.raise_for_status = MagicMock()

    import httpx
    with patch("httpx.AsyncClient") as mock_cls:
        mock_inst = AsyncMock()
        mock_inst.post = AsyncMock(return_value=response)
        mock_cls.return_value = mock_inst

        client = A2AClient("http://localhost:8000")
        with pytest.raises(TaskNotFoundError):
            await client.send_message(
                {"role": "user", "parts": [{"kind": "text", "text": "hi"}]},
                metadata={"skillId": "x"},
            )

async def test_send_message_rpc_error_not_cancelable():
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"jsonrpc": "2.0", "id": "1", "error": {"code": -32002, "message": "Not cancelable"}}
    response.raise_for_status = MagicMock()

    import httpx
    with patch("httpx.AsyncClient") as mock_cls:
        mock_inst = AsyncMock()
        mock_inst.post = AsyncMock(return_value=response)
        mock_cls.return_value = mock_inst

        client = A2AClient("http://localhost:8000")
        with pytest.raises(TaskNotCancelableError):
            await client.cancel_task("task-1")

async def test_send_message_connection_error():
    import httpx
    with patch("httpx.AsyncClient") as mock_cls:
        mock_inst = AsyncMock()
        mock_inst.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_cls.return_value = mock_inst

        client = A2AClient("http://localhost:8000")
        with pytest.raises(A2AConnectionError):
            await client.send_message(
                {"role": "user", "parts": [{"kind": "text", "text": "hi"}]},
                metadata={"skillId": "x"},
            )

# --- get_task ---
async def test_get_task_success(task_dict):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"jsonrpc": "2.0", "id": "1", "result": task_dict}
    response.raise_for_status = MagicMock()

    import httpx
    with patch("httpx.AsyncClient") as mock_cls:
        mock_inst = AsyncMock()
        mock_inst.post = AsyncMock(return_value=response)
        mock_cls.return_value = mock_inst

        client = A2AClient("http://localhost:8000")
        result = await client.get_task("task-1")
        assert result == task_dict

# --- context manager ---
async def test_context_manager_close():
    import httpx
    with patch("httpx.AsyncClient") as mock_cls:
        mock_inst = AsyncMock()
        mock_cls.return_value = mock_inst

        async with A2AClient("http://localhost:8000") as client:
            pass
        mock_inst.aclose.assert_called_once()

# --- auth header ---
def test_auth_header_set():
    import httpx
    with patch("httpx.AsyncClient") as mock_cls:
        A2AClient("http://localhost:8000", auth="Bearer mytoken")
        call_kwargs = mock_cls.call_args[1]
        headers = call_kwargs.get("headers", {})
        assert headers.get("Authorization") == "Bearer mytoken"

def test_no_auth_no_header():
    import httpx
    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value = MagicMock()
        A2AClient("http://localhost:8000")
        call_kwargs = mock_cls.call_args[1] if mock_cls.call_args else {}
        headers = call_kwargs.get("headers", {})
        assert "Authorization" not in headers


# --- stream_message --- (T4)

async def test_stream_message_yields_events_and_terminates_on_final():
    """T4: stream_message yields events and stops when final=true is received."""
    import httpx
    from unittest.mock import AsyncMock, MagicMock, patch
    import json

    # Build fake SSE lines: two events, second has final=true
    lines = [
        'data: {"type": "TaskStatusUpdateEvent", "taskId": "t1", "final": false}',
        'data: {"type": "TaskStatusUpdateEvent", "taskId": "t1", "final": true}',
        'data: {"type": "TaskStatusUpdateEvent", "taskId": "t1", "final": false}',  # should not be yielded
    ]

    async def _fake_aiter_lines():
        for line in lines:
            yield line

    mock_response = MagicMock()
    mock_response.aiter_lines = _fake_aiter_lines

    def _fake_stream(*args, **kwargs):
        class _CM:
            async def __aenter__(self_cm):
                return mock_response
            async def __aexit__(self_cm, *exc):
                pass
        return _CM()

    with patch("httpx.AsyncClient") as mock_cls:
        mock_inst = MagicMock()
        mock_inst.stream = _fake_stream
        mock_cls.return_value = mock_inst

        client = A2AClient("http://localhost:8000")
        events = []
        async for event in client.stream_message({"role": "user", "parts": []}):
            events.append(event)

    assert len(events) == 2
    assert events[-1]["final"] is True


async def test_stream_message_terminates_on_final_in_result_envelope():
    """T4: stream_message stops when final=true is nested inside a result envelope."""
    import json

    lines = [
        'data: {"jsonrpc":"2.0","id":"1","result":{"type":"TaskStatusUpdateEvent","final":true}}',
    ]

    async def _fake_aiter_lines():
        for line in lines:
            yield line

    mock_response = MagicMock()
    mock_response.aiter_lines = _fake_aiter_lines

    def _fake_stream(*args, **kwargs):
        class _CM:
            async def __aenter__(self_cm):
                return mock_response
            async def __aexit__(self_cm, *exc):
                pass
        return _CM()

    with patch("httpx.AsyncClient") as mock_cls:
        mock_inst = MagicMock()
        mock_inst.stream = _fake_stream
        mock_cls.return_value = mock_inst

        client = A2AClient("http://localhost:8000")
        events = []
        async for event in client.stream_message({"role": "user", "parts": []}):
            events.append(event)

    assert len(events) == 1
    assert events[0]["result"]["final"] is True


async def test_stream_message_raises_on_request_error():
    """T4: stream_message raises A2AConnectionError on httpx.RequestError."""
    import httpx

    def _bad_stream(*args, **kwargs):
        raise httpx.ConnectError("refused")

    with patch("httpx.AsyncClient") as mock_cls:
        mock_inst = MagicMock()
        mock_inst.stream = _bad_stream
        mock_cls.return_value = mock_inst

        client = A2AClient("http://localhost:8000")
        with pytest.raises(A2AConnectionError):
            async for _ in client.stream_message({"role": "user", "parts": []}):
                pass
