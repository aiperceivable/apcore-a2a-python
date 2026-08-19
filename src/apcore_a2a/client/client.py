"""A2AClient: HTTP client for remote A2A agents."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from urllib.parse import urlparse
from uuid import uuid4

import httpx

from apcore_a2a.client.card_fetcher import AgentCardFetcher
from apcore_a2a.client.exceptions import (
    A2AConnectionError,
    A2AServerError,
    TaskNotCancelableError,
    TaskNotFoundError,
)

_JSONRPC_ERRORS = {
    -32001: TaskNotFoundError,
    -32002: TaskNotCancelableError,
}


def _raise_jsonrpc_error(error: dict) -> None:
    code = error.get("code", -32603)
    message = error.get("message", "Server error")
    exc_class = _JSONRPC_ERRORS.get(code, A2AServerError)
    if exc_class is TaskNotFoundError:
        raise TaskNotFoundError()
    if exc_class is TaskNotCancelableError:
        raise TaskNotCancelableError()
    raise A2AServerError(message, code=code)


#: Terminal A2A 1.0 task states; streaming stops when one is observed.
TERMINAL_STATES = frozenset(
    {
        "TASK_STATE_COMPLETED",
        "TASK_STATE_FAILED",
        "TASK_STATE_CANCELED",
        "TASK_STATE_REJECTED",
    }
)


def _raise_if_stream_error(frame: dict) -> None:
    """Raise if ``frame`` is a JSON-RPC error frame rather than an event.

    A mid-stream failure arrives as its own frame — upstream tags it
    ``event: error`` and puts a JSON-RPC error response in ``data:``. Envelope
    unwrapping only looks for ``result``, so without this the frame was yielded
    as though it were an event and the failure was lost, while the
    non-streaming path raised for a byte-identical payload. Uses the same
    mapping, so a caller gets ``TaskNotFoundError`` / ``TaskNotCancelableError``
    on both paths.
    """
    if "jsonrpc" in frame and "error" in frame:
        _raise_jsonrpc_error(frame["error"])


def _unwrap_stream_envelope(frame: dict) -> dict:
    """Return the event carried by a JSON-RPC SSE frame.

    Every ``data:`` line on the stream is a full JSON-RPC response whose
    ``result`` is the event. Frames that are not enveloped are passed through
    unchanged.
    """
    if "jsonrpc" in frame and "result" in frame:
        result = frame["result"]
        return result if isinstance(result, dict) else frame
    return frame


def _is_terminal_event(event: dict) -> bool:
    """Whether ``event`` is a terminal ``statusUpdate``.

    A2A 1.0 removed the ``final`` flag that 0.3 used to mark the last event, so
    the terminal state itself is the signal.
    """
    status = event.get("statusUpdate")
    if not isinstance(status, dict):
        return False
    state = status.get("status", {})
    return isinstance(state, dict) and state.get("state") in TERMINAL_STATES


class A2AClient:
    def __init__(
        self,
        url: str,
        *,
        auth: str | None = None,
        timeout: float = 30.0,
        card_ttl: float = 300.0,
    ) -> None:
        """Construct A2A client for a remote agent.

        Raises:
            ValueError: If url is not a valid HTTP/HTTPS URL.
        """
        self._validate_url(url)
        self._url = url.rstrip("/")
        headers: dict[str, str] = {}
        if auth:
            headers["Authorization"] = auth
        self._http = httpx.AsyncClient(timeout=timeout, headers=headers)
        self._card_fetcher = AgentCardFetcher(self._http, self._url, ttl=card_ttl)

    def _validate_url(self, url: str) -> None:
        """Validate url is well-formed HTTP/HTTPS. Raises ValueError."""
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(f"Invalid A2A agent URL: {url!r} (must be http:// or https://)")

    @property
    async def agent_card(self) -> dict:
        """Fetch and cache the remote Agent Card (TTL-based)."""
        return await self._card_fetcher.fetch()

    async def send_message(
        self,
        message: dict,
        *,
        metadata: dict | None = None,
        context_id: str | None = None,
    ) -> dict:
        """Send message/send JSON-RPC request. Returns Task dict.

        Raises:
            TaskNotFoundError: JSON-RPC error -32001.
            A2AServerError: JSON-RPC error -32603 (internal server error).
            A2AConnectionError: Network-level failure or HTTP error.
        """
        params: dict = {"message": message, "metadata": metadata or {}}
        if context_id:
            params["contextId"] = context_id
        return await self._jsonrpc_call("message/send", params)

    async def get_task(self, task_id: str) -> dict:
        """Retrieve task state via tasks/get."""
        return await self._jsonrpc_call("tasks/get", {"id": task_id})

    async def cancel_task(self, task_id: str) -> dict:
        """Cancel a task via tasks/cancel.

        Raises:
            TaskNotFoundError: -32001 if task not found.
            TaskNotCancelableError: -32002 if task is in terminal state.
        """
        return await self._jsonrpc_call("tasks/cancel", {"id": task_id})

    async def list_tasks(
        self,
        context_id: str | None = None,
        limit: int = 50,
    ) -> dict:
        """List tasks via ``ListTasks``.

        A2A 1.0 names this method ``ListTasks``; 0.3 had no task-listing method
        at all. The ``tasks/list`` spelling used here until 0.5.0 was neither, so
        it reached only this project's own Rust server.

        ``limit`` stays the friendly parameter name but goes on the wire as
        ``pageSize``, which is what ``ListTasksRequest`` declares (alongside
        ``pageToken``, ``status``, ``historyLength``, …). Sending ``limit``
        earned an ``-32602`` from both SDK-backed servers.

        Returns {tasks: [...], nextPageToken: str, totalSize: int}.
        """
        params: dict = {"pageSize": limit}
        if context_id:
            params["contextId"] = context_id
        return await self._jsonrpc_call("ListTasks", params, a2a_version="1.0")

    async def discover(self) -> dict:
        """Convenience alias: fetch and return the Agent Card."""
        return await self._card_fetcher.fetch()

    async def stream_message(
        self,
        message: dict,
        *,
        metadata: dict | None = None,
        context_id: str | None = None,
    ) -> AsyncGenerator[dict, None]:
        """Send message/stream and yield parsed SSE event dicts.

        Yields:
            The event carried by each frame — a ``statusUpdate`` /
            ``artifactUpdate`` / ``task`` object, unwrapped from the JSON-RPC
            response that carries it on the wire.

        Terminates when the stream closes or a terminal ``TASK_STATE_*`` status
        is observed. A2A 1.0 has no ``final`` flag; the previous code looked for
        one and so never stopped early.
        """
        params: dict = {"message": message, "metadata": metadata or {}}
        if context_id:
            params["contextId"] = context_id
        body = {
            "jsonrpc": "2.0",
            "id": str(uuid4()),
            "method": "message/stream",
            "params": params,
        }
        try:
            async with self._http.stream("POST", f"{self._url}/", json=body) as response:
                async for line in response.aiter_lines():
                    line = line.rstrip()
                    # Skip keepalive comments (": ...") and blank separators.
                    if not line.startswith("data:"):
                        continue
                    try:
                        frame = json.loads(line[len("data:") :].lstrip())
                    except json.JSONDecodeError:
                        continue
                    _raise_if_stream_error(frame)
                    event = _unwrap_stream_envelope(frame)
                    terminal = _is_terminal_event(event)
                    yield event
                    if terminal:
                        return
        except httpx.RequestError as e:
            raise A2AConnectionError(str(e)) from e

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()

    async def __aenter__(self) -> A2AClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    async def _jsonrpc_call(self, method: str, params: dict, *, a2a_version: str | None = None) -> dict:
        """POST JSON-RPC request. Returns result dict or raises typed error.

        ``a2a_version`` sets the ``A2A-Version`` header. Both upstream SDKs treat
        a request without it as v0.3 (spec section 3.6.2) and refuse 1.0 method
        names in that mode with ``-32009``, so methods that exist only in 1.0
        must declare ``"1.0"``. Methods 0.3 also has are left unversioned, so a
        0.3 server keeps working.
        """
        body = {"jsonrpc": "2.0", "id": str(uuid4()), "method": method, "params": params}
        headers = {"A2A-Version": a2a_version} if a2a_version else None
        try:
            response = await self._http.post(f"{self._url}/", json=body, headers=headers)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise A2AConnectionError(str(e)) from e
        except httpx.RequestError as e:
            raise A2AConnectionError(str(e)) from e
        data = response.json()
        if "error" in data:
            _raise_jsonrpc_error(data["error"])
        return data["result"]
