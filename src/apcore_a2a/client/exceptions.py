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


class GovernanceRefusedError(A2AClientError):
    """Base class for the three governance refusals (srs FR-ERR-003/009/010).

    Distinguishing these from :class:`A2AServerError` is the point of the typed
    classes: a refusal is not a transient failure, and an agent that backs off
    and retries one will be refused identically for as long as it keeps trying.
    Before the server side of this change, an ACL denial arrived as
    :class:`TaskNotFoundError` and an approval denial as :class:`A2AServerError`
    — both naming a different failure than the one that happened.
    """

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


class AccessDeniedError(GovernanceRefusedError):
    """JSON-RPC -32040: the ACL refused this caller. Terminal."""

    def __init__(self, message: str = "Access denied") -> None:
        super().__init__(message, code=-32040)


class ApprovalDeniedError(GovernanceRefusedError):
    """JSON-RPC -32041: a human explicitly refused this call. Terminal."""

    def __init__(self, message: str = "Approval denied") -> None:
        super().__init__(message, code=-32041)


class ApprovalTimeoutError(GovernanceRefusedError):
    """JSON-RPC -32042: the approval expired unanswered.

    Unlike the other two refusals, a fresh submission may legitimately be
    approved — nobody refused, nobody answered.
    """

    def __init__(self, message: str = "Approval timed out") -> None:
        super().__init__(message, code=-32042)


class A2AServerError(A2AClientError):
    """JSON-RPC -32603 or other server error."""

    def __init__(self, message: str, code: int = -32603) -> None:
        super().__init__(message)
        self.code = code
