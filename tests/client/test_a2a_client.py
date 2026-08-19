"""Tests for A2AClient."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apcore_a2a.client.client import A2AClient
from apcore_a2a.client.exceptions import (
    A2AClientError,
    A2AConnectionError,
    A2ADiscoveryError,
    A2AServerError,
    TaskNotCancelableError,
    TaskNotFoundError,
)


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

    with patch("httpx.AsyncClient") as mock_cls:
        mock_inst = AsyncMock()
        mock_inst.post = AsyncMock(return_value=response)
        mock_cls.return_value = mock_inst

        client = A2AClient("http://localhost:8000")
        result = await client.get_task("task-1")
        assert result == task_dict


# --- context manager ---
async def test_context_manager_close():
    with patch("httpx.AsyncClient") as mock_cls:
        mock_inst = AsyncMock()
        mock_cls.return_value = mock_inst

        async with A2AClient("http://localhost:8000"):
            pass
        mock_inst.aclose.assert_called_once()


# --- auth header ---
def test_auth_header_set():
    with patch("httpx.AsyncClient") as mock_cls:
        A2AClient("http://localhost:8000", auth="Bearer mytoken")
        call_kwargs = mock_cls.call_args[1]
        headers = call_kwargs.get("headers", {})
        assert headers.get("Authorization") == "Bearer mytoken"


def test_no_auth_no_header():
    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value = MagicMock()
        A2AClient("http://localhost:8000")
        call_kwargs = mock_cls.call_args[1] if mock_cls.call_args else {}
        headers = call_kwargs.get("headers", {})
        assert "Authorization" not in headers


# --- stream_message --- (T4)


async def _drive_stream(lines: list[str]) -> list[dict]:
    """Run ``stream_message`` against a canned SSE body and collect what it yields."""
    from unittest.mock import MagicMock, patch

    async def _fake_aiter_lines():
        for line in lines:
            yield line

    mock_response = MagicMock()
    mock_response.aiter_lines = _fake_aiter_lines

    def _fake_stream(*args, **kwargs):
        class _CM:
            async def __aenter__(self):
                return mock_response

            async def __aexit__(self, *exc):
                pass

        return _CM()

    with patch("httpx.AsyncClient") as mock_cls:
        mock_inst = MagicMock()
        mock_inst.stream = _fake_stream
        mock_cls.return_value = mock_inst

        client = A2AClient("http://localhost:8000")
        return [event async for event in client.stream_message({"role": "user", "parts": []})]


def _frame(state: str) -> str:
    """One A2A 1.0 SSE frame: a JSON-RPC response carrying a statusUpdate."""
    return (
        'data: {"jsonrpc":"2.0","id":"req-1","result":{"statusUpdate":'
        f'{{"taskId":"t1","status":{{"state":"{state}"}}}}}}}}'
    )


async def test_stream_message_unwraps_the_jsonrpc_envelope():
    """T4: each frame is a JSON-RPC response; the event under `result` is yielded."""
    events = await _drive_stream([_frame("TASK_STATE_WORKING")])

    assert len(events) == 1
    # The envelope is gone — callers get the event, as the docstring promises.
    assert "jsonrpc" not in events[0]
    assert events[0]["statusUpdate"]["status"]["state"] == "TASK_STATE_WORKING"


async def test_stream_message_stops_at_a_terminal_status():
    """T4: a terminal TASK_STATE_* ends the stream, and is itself yielded."""
    events = await _drive_stream(
        [
            _frame("TASK_STATE_SUBMITTED"),
            _frame("TASK_STATE_WORKING"),
            _frame("TASK_STATE_COMPLETED"),
            _frame("TASK_STATE_WORKING"),  # after the terminal one: must not appear
        ]
    )

    states = [e["statusUpdate"]["status"]["state"] for e in events]
    assert states == ["TASK_STATE_SUBMITTED", "TASK_STATE_WORKING", "TASK_STATE_COMPLETED"]


async def test_stream_message_ignores_the_removed_final_flag():
    """T4: `final` is an A2A 0.3 construct — 1.0 removed it, so it must not stop the stream.

    The previous implementation keyed on `final` alone, which no 1.0 server ever
    sends, so it never terminated early; and a stray `final` must not terminate
    early either.
    """
    stray_final = (
        'data: {"jsonrpc":"2.0","id":"req-1","result":{"statusUpdate":'
        '{"taskId":"t1","final":true,"status":{"state":"TASK_STATE_WORKING"}}}}'
    )
    events = await _drive_stream([stray_final, _frame("TASK_STATE_COMPLETED")])

    assert len(events) == 2, "a `final` flag must not end the stream on its own"


async def test_stream_message_raises_on_a_mid_stream_error_frame():
    """T4: a JSON-RPC error frame ends the stream by raising, not by yielding.

    Upstream reports a mid-stream failure as its own frame (tagged
    ``event: error``). Unwrapping only looks for ``result``, so before this the
    frame was handed to the caller as if it were an event and the failure was
    lost — while the non-streaming path raised for the same payload. The error
    is mapped exactly as there, so this is a ``TaskNotFoundError``, not a
    generic one.
    """
    from unittest.mock import MagicMock, patch

    import pytest

    from apcore_a2a.client.exceptions import TaskNotFoundError

    lines = [
        _frame("TASK_STATE_WORKING"),
        'data: {"jsonrpc":"2.0","id":"req-1",'
        '"error":{"code":-32001,"message":"Task not found"}}',
    ]

    async def _fake_aiter_lines():
        for line in lines:
            yield line

    mock_response = MagicMock()
    mock_response.aiter_lines = _fake_aiter_lines

    def _fake_stream(*args, **kwargs):
        class _CM:
            async def __aenter__(self):
                return mock_response

            async def __aexit__(self, *exc):
                pass

        return _CM()

    with patch("httpx.AsyncClient") as mock_cls:
        mock_inst = MagicMock()
        mock_inst.stream = _fake_stream
        mock_cls.return_value = mock_inst

        client = A2AClient("http://localhost:8000")
        seen = []
        with pytest.raises(TaskNotFoundError):
            async for event in client.stream_message({"role": "user", "parts": []}):
                seen.append(event)

    # Events before the error frame still reached the caller.
    assert len(seen) == 1
    assert seen[0]["statusUpdate"]["status"]["state"] == "TASK_STATE_WORKING"


async def test_stream_message_skips_keepalive_and_blank_lines():
    """T4: SSE comment lines (": ...") and blank separators carry no event."""
    events = await _drive_stream(
        ["", ": keepalive", _frame("TASK_STATE_COMPLETED"), ""]
    )

    assert len(events) == 1


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
