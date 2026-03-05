"""Targeted tests to boost coverage for uncovered paths across several modules."""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from a2a.types import DataPart, Part, TextPart
from apcore_a2a.adapters.schema import SchemaConverter


# ── adapters/parts.py ──────────────────────────────────────────────────────────

def test_parts_to_input_multiple_parts_raises():
    from apcore_a2a.adapters.parts import PartConverter
    pc = PartConverter(SchemaConverter())
    parts = [
        Part(root=TextPart(text="a")),
        Part(root=TextPart(text="b")),
    ]
    with pytest.raises(ValueError, match="Multiple parts"):
        pc.parts_to_input(parts, None)


def test_parts_to_input_unsupported_kind_raises():
    from apcore_a2a.adapters.parts import PartConverter
    from a2a.types import FilePart, FileWithUri
    pc = PartConverter(SchemaConverter())
    file_part = Part(root=FilePart(file=FileWithUri(uri="http://example.com/v.mp4", mime_type="video/mp4")))
    with pytest.raises(ValueError):
        pc.parts_to_input([file_part], None)


# ── adapters/errors.py ─────────────────────────────────────────────────────────

class _ApCoreError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def test_error_mapper_module_timeout():
    from apcore_a2a.adapters.errors import ErrorMapper
    mapper = ErrorMapper()
    result = mapper.to_jsonrpc_error(_ApCoreError("MODULE_TIMEOUT", "timed out"))
    assert result["code"] == -32603
    assert "timeout" in result["message"].lower()


def test_error_mapper_execution_timeout_code():
    from apcore_a2a.adapters.errors import ErrorMapper
    mapper = ErrorMapper()
    result = mapper.to_jsonrpc_error(_ApCoreError("EXECUTION_TIMEOUT", "execution timeout"))
    assert result["code"] == -32603


def test_error_mapper_call_depth_exceeded():
    from apcore_a2a.adapters.errors import ErrorMapper
    mapper = ErrorMapper()
    result = mapper.to_jsonrpc_error(_ApCoreError("CALL_DEPTH_EXCEEDED", "too deep"))
    assert result["code"] == -32603
    assert "safety" in result["message"].lower()


def test_error_mapper_invalid_input():
    from apcore_a2a.adapters.errors import ErrorMapper
    mapper = ErrorMapper()
    result = mapper.to_jsonrpc_error(_ApCoreError("INVALID_INPUT", "bad schema"))
    assert result["code"] == -32602
    assert "Invalid input" in result["message"]


# ── adapters/schema.py ─────────────────────────────────────────────────────────

def test_detect_root_type_none_schema():
    from apcore_a2a.adapters.schema import SchemaConverter
    sc = SchemaConverter()
    assert sc.detect_root_type(None) == "unknown"


def test_detect_root_type_empty_dict():
    from apcore_a2a.adapters.schema import SchemaConverter
    sc = SchemaConverter()
    assert sc.detect_root_type({}) == "unknown"


def test_detect_root_type_string():
    from apcore_a2a.adapters.schema import SchemaConverter
    sc = SchemaConverter()
    assert sc.detect_root_type({"type": "string"}) == "string"


def test_detect_root_type_object_explicit():
    from apcore_a2a.adapters.schema import SchemaConverter
    sc = SchemaConverter()
    assert sc.detect_root_type({"type": "object"}) == "object"


def test_detect_root_type_via_properties():
    from apcore_a2a.adapters.schema import SchemaConverter
    sc = SchemaConverter()
    assert sc.detect_root_type({"properties": {"x": {"type": "integer"}}}) == "object"


def test_detect_root_type_unknown_type():
    from apcore_a2a.adapters.schema import SchemaConverter
    sc = SchemaConverter()
    assert sc.detect_root_type({"type": "integer"}) == "unknown"


# ── client/client.py ──────────────────────────────────────────────────────────

@pytest.fixture
def mock_client_with_http():
    """A2AClient with a mocked httpx.AsyncClient."""
    from apcore_a2a.client.client import A2AClient
    client = A2AClient("http://localhost:8000")
    mock_http = AsyncMock()
    client._http = mock_http
    client._card_fetcher._http = mock_http
    return client, mock_http


def _make_jsonrpc_response(result=None, error=None):
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    if error:
        mock_resp.json.return_value = {"jsonrpc": "2.0", "id": "1", "error": error}
    else:
        mock_resp.json.return_value = {"jsonrpc": "2.0", "id": "1", "result": result or {}}
    return mock_resp


async def test_send_message_with_context_id(mock_client_with_http):
    """Tests the params['contextId'] branch in send_message."""
    client, mock_http = mock_client_with_http
    mock_http.post = AsyncMock(return_value=_make_jsonrpc_response(result={"id": "t1"}))
    result = await client.send_message(
        {"role": "user", "parts": []},
        context_id="ctx-123",
    )
    assert result == {"id": "t1"}
    call_kwargs = mock_http.post.call_args
    body = call_kwargs[1]["json"]
    assert body["params"]["contextId"] == "ctx-123"


async def test_list_tasks_with_context_id(mock_client_with_http):
    """Tests the contextId branch in list_tasks."""
    client, mock_http = mock_client_with_http
    mock_http.post = AsyncMock(return_value=_make_jsonrpc_response(result={"tasks": []}))
    result = await client.list_tasks(context_id="ctx-abc", limit=10)
    assert result == {"tasks": []}
    call_kwargs = mock_http.post.call_args
    body = call_kwargs[1]["json"]
    assert body["params"]["contextId"] == "ctx-abc"


async def test_discover_returns_agent_card(mock_client_with_http):
    """Tests the discover() method (covers card_fetcher.fetch path)."""
    client, mock_http = mock_client_with_http
    card = {"name": "Test Agent", "version": "1.0"}
    client._card_fetcher.fetch = AsyncMock(return_value=card)
    result = await client.discover()
    assert result == card


async def test_agent_card_property(mock_client_with_http):
    """Tests the agent_card async property."""
    client, mock_http = mock_client_with_http
    card = {"name": "Agent", "version": "0.1"}
    client._card_fetcher.fetch = AsyncMock(return_value=card)
    result = await client.agent_card
    assert result == card


async def test_jsonrpc_call_raises_a2a_server_error_for_unknown_code(mock_client_with_http):
    """Tests A2AServerError raised for non-special error codes."""
    from apcore_a2a.client.exceptions import A2AServerError
    client, mock_http = mock_client_with_http
    error = {"code": -32603, "message": "Internal error"}
    mock_http.post = AsyncMock(return_value=_make_jsonrpc_response(error=error))
    with pytest.raises(A2AServerError):
        await client.send_message({"role": "user", "parts": []})


async def test_jsonrpc_call_raises_connection_error_on_http_status_error(mock_client_with_http):
    """Tests HTTPStatusError → A2AConnectionError."""
    import httpx
    from apcore_a2a.client.exceptions import A2AConnectionError
    client, mock_http = mock_client_with_http
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "404", request=MagicMock(), response=MagicMock()
    )
    mock_http.post = AsyncMock(return_value=mock_resp)
    with pytest.raises(A2AConnectionError):
        await client.send_message({"role": "user", "parts": []})


# ── client/exceptions.py ─────────────────────────────────────────────────────

def test_a2a_server_error_with_code():
    from apcore_a2a.client.exceptions import A2AServerError
    err = A2AServerError("boom", code=-32603)
    assert err.code == -32603
    assert str(err) == "boom"


def test_a2a_server_error_default_code():
    from apcore_a2a.client.exceptions import A2AServerError
    err = A2AServerError("boom")
    assert err.code == -32603
