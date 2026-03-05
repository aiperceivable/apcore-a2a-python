"""A2AClient: HTTP client for remote A2A agents."""
from __future__ import annotations
import json
from typing import AsyncGenerator
from urllib.parse import urlparse
from uuid import uuid4
import httpx
from apcore_a2a.client.card_fetcher import AgentCardFetcher
from apcore_a2a.client.exceptions import (
    A2AClientError,
    A2AConnectionError,
    TaskNotFoundError,
    TaskNotCancelableError,
    A2AServerError,
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
        """List tasks via tasks/list.
        Returns {tasks: [...], nextCursor: str|None}.
        """
        params: dict = {"limit": limit}
        if context_id:
            params["contextId"] = context_id
        return await self._jsonrpc_call("tasks/list", params)

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
            TaskStatusUpdateEvent or TaskArtifactUpdateEvent dicts.
        Terminates when stream closes or event with final=true received.
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
                    if line.startswith("data: "):
                        try:
                            data = json.loads(line[6:])
                            yield data
                            # final may be a top-level field on the event object,
                            # or nested inside a JSON-RPC result envelope
                            final = data.get("final") or data.get("result", {}).get("final")
                            if final:
                                return
                        except json.JSONDecodeError:
                            continue
        except httpx.RequestError as e:
            raise A2AConnectionError(str(e)) from e

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()

    async def __aenter__(self) -> "A2AClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    async def _jsonrpc_call(self, method: str, params: dict) -> dict:
        """POST JSON-RPC request. Returns result dict or raises typed error."""
        body = {"jsonrpc": "2.0", "id": str(uuid4()), "method": method, "params": params}
        try:
            response = await self._http.post(f"{self._url}/", json=body)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise A2AConnectionError(str(e)) from e
        except httpx.RequestError as e:
            raise A2AConnectionError(str(e)) from e
        data = response.json()
        if "error" in data:
            _raise_jsonrpc_error(data["error"])
        return data["result"]
