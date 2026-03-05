"""Client-side exceptions for A2A operations."""
from __future__ import annotations


class A2AClientError(Exception):
    """Base class for all A2A client errors."""


class A2AConnectionError(A2AClientError):
    """Network-level failure: connection refused, timeout, DNS error."""


class A2ADiscoveryError(A2AClientError):
    """Agent Card fetch failed: HTTP error or invalid JSON."""


class TaskNotFoundError(A2AClientError):
    """JSON-RPC -32001: Task not found."""

    def __init__(self, task_id: str | None = None) -> None:
        msg = f"Task not found: {task_id}" if task_id else "Task not found"
        super().__init__(msg)
        self.task_id = task_id


class TaskNotCancelableError(A2AClientError):
    """JSON-RPC -32002: Task is in a terminal state."""

    def __init__(self, state: str | None = None) -> None:
        msg = f"Task not cancelable: state={state}" if state else "Task not cancelable"
        super().__init__(msg)
        self.state = state


class A2AServerError(A2AClientError):
    """JSON-RPC -32603 or other server error."""

    def __init__(self, message: str, code: int = -32603) -> None:
        super().__init__(message)
        self.code = code
