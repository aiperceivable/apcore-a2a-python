"""ErrorMapper: maps apcore exceptions to A2A JSON-RPC error dicts."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from apcore.errors import ErrorCodes

logger = logging.getLogger(__name__)

# JSON-RPC error codes
_CODE_METHOD_NOT_FOUND = -32601  # Skill/module not found
_CODE_INVALID_PARAMS = -32602  # Schema validation / invalid input
_CODE_INTERNAL_ERROR = -32603  # Internal / timeout / safety errors
_CODE_TASK_NOT_FOUND = -32001  # Unknown task id, or a task owned by another principal

# Governance refusal codes (srs FR-ERR-003 / FR-ERR-009 / FR-ERR-010).
#
# A2A 1.0 reserves -32001..-32009; JSON-RPC 2.0 leaves -32000..-32099 to the
# implementation. These three sit above A2A's reserved block, with room for it
# to grow, and are the "JSON-RPC custom error" A2A §13.2 names as the example
# for this binding.
#
# apcore distinguishes these three refusals from each other and from every other
# failure. Collapsing them onto -32001 (which means "unknown or non-owned task
# id") or -32603 (which every agent reads as "retry me") told the caller a
# *different* failure had happened, one whose correct response is the opposite
# of the real one.
_CODE_ACCESS_DENIED = -32040
_CODE_APPROVAL_DENIED = -32041
_CODE_APPROVAL_TIMEOUT = -32042

# The three governance codes, with the fixed message each reports by default.
# Ordered dict rather than a set: the message is part of the mapping.
_GOVERNANCE_REFUSALS: dict[str, str] = {
    ErrorCodes.ACL_DENIED: "Access denied",
    ErrorCodes.APPROVAL_DENIED: "Approval denied",
    ErrorCodes.APPROVAL_TIMEOUT: "Approval timed out",
}

# Public alias for the server layer, which needs the same partition to decide
# TASK_STATE_REJECTED (srs FR-ERR-012) without re-deriving it.
GOVERNANCE_REFUSAL_CODES: frozenset[str] = frozenset(_GOVERNANCE_REFUSALS)

_GOVERNANCE_CODES: dict[str, int] = {
    ErrorCodes.ACL_DENIED: _CODE_ACCESS_DENIED,
    ErrorCodes.APPROVAL_DENIED: _CODE_APPROVAL_DENIED,
    ErrorCodes.APPROVAL_TIMEOUT: _CODE_APPROVAL_TIMEOUT,
}


class ErrorMapper:
    """Maps apcore exceptions to A2A JSON-RPC error dicts.

    Security note: a governance refusal conveys its *class* and suppresses its
    *detail*; internal errors never expose file paths, caller identity, or stack
    traces to the caller.
    """

    def __init__(self, *, disclose_refusal_reason: bool = False) -> None:
        """Args:
        disclose_refusal_reason: Forward apcore's own message for the three
            governance refusal codes instead of the fixed per-class string
            (srs FR-ERR-011). Off by default. The code never changes with the
            flag — what a refusal *is* does not depend on how much a deployment
            chooses to say about it.
        """
        self._disclose_refusal_reason = disclose_refusal_reason

    @property
    def disclose_refusal_reason(self) -> bool:
        """Whether governance refusals forward apcore's own reason."""
        return self._disclose_refusal_reason

    def format(self, error: Exception, context: object = None) -> dict[str, Any]:
        """ErrorFormatter protocol implementation for apcore ErrorFormatterRegistry.

        Args:
            error: The error to format.
            context: Optional context (unused, present for protocol compliance).

        Returns:
            Dict with "code" (int) and "message" (str) keys.
        """
        return self.to_jsonrpc_error(error)

    def to_jsonrpc_error(self, error: Exception) -> dict[str, Any]:
        """Convert an exception to an A2A JSON-RPC error dict.

        Args:
            error: Exception to convert.

        Returns:
            Dict with "code" (int) and "message" (str) keys.
        """
        # Log full detail for server-side diagnosis
        logger.error("A2A error: %s", error, exc_info=True)

        # Check for apcore-style errors with a .code attribute
        error_code = getattr(error, "code", None)

        if error_code is not None:
            return self._handle_apcore_error(error, error_code)

        # asyncio.TimeoutError
        if isinstance(error, asyncio.TimeoutError):
            return {"code": _CODE_INTERNAL_ERROR, "message": "Execution timeout"}

        # All other exceptions
        return {"code": _CODE_INTERNAL_ERROR, "message": "Internal server error"}

    def _handle_apcore_error(self, error: Exception, error_code: str) -> dict[str, Any]:
        """Handle an apcore error with a .code attribute.

        Args:
            error: The apcore exception.
            error_code: The string error code from error.code.

        Returns:
            JSON-RPC error dict.
        """
        if error_code == ErrorCodes.MODULE_NOT_FOUND:
            # Extract module ID from message if possible
            message = self._sanitize_message(getattr(error, "message", str(error)))
            return {"code": _CODE_METHOD_NOT_FOUND, "message": message}

        if error_code == ErrorCodes.SCHEMA_VALIDATION_ERROR:
            # apcore raises the one code for output validation too, which the
            # caller can do nothing about — see is_server_side_schema_error.
            if is_server_side_schema_error(getattr(error, "message", str(error))):
                return {"code": _CODE_INTERNAL_ERROR, "message": "Internal server error"}
            message = self._sanitize_message(getattr(error, "message", str(error)))
            return {"code": _CODE_INVALID_PARAMS, "message": message}

        if error_code == ErrorCodes.GENERAL_INVALID_INPUT:
            description = self._sanitize_message(getattr(error, "message", str(error)))
            return {"code": _CODE_INVALID_PARAMS, "message": f"Invalid input: {description}"}

        if error_code in _GOVERNANCE_REFUSALS:
            # The A2A spec §13.2 MUST NOT forbids revealing *the existence of a
            # resource*, not the *class* of failure. A fixed "Access denied" /
            # "Approval denied" / "Approval timed out" names no caller, target,
            # approver or rule, so it discloses nothing — a caller that named a
            # skill already held that id — while still telling an agent to stop
            # rather than retry.
            #
            # APPROVAL_PENDING is deliberately absent: it is a resumable pause
            # carrying the approval_id the caller resumes with, handled by the
            # executor before it ever reaches here (srs FR-EXE-002).
            return {
                "code": _GOVERNANCE_CODES[error_code],
                "message": self._refusal_message(error, error_code),
            }

        if error_code == ErrorCodes.MODULE_TIMEOUT:
            return {"code": _CODE_INTERNAL_ERROR, "message": "Execution timeout"}

        if error_code == ErrorCodes.EXECUTION_CANCELLED:
            return {"code": _CODE_INTERNAL_ERROR, "message": "Execution cancelled"}

        if error_code in (
            ErrorCodes.CALL_DEPTH_EXCEEDED,
            ErrorCodes.CIRCULAR_CALL,
            ErrorCodes.CALL_FREQUENCY_EXCEEDED,
        ):
            return {"code": _CODE_INTERNAL_ERROR, "message": "Safety limit exceeded"}

        if error_code in (ErrorCodes.CIRCUIT_BREAKER_OPEN, ErrorCodes.TASK_LIMIT_EXCEEDED):
            return {"code": _CODE_INTERNAL_ERROR, "message": "Service temporarily unavailable"}

        if error_code == ErrorCodes.MODULE_DISABLED:
            return {"code": _CODE_INTERNAL_ERROR, "message": "Module is currently disabled"}

        if error_code in (
            ErrorCodes.CONFIG_NAMESPACE_DUPLICATE,
            ErrorCodes.CONFIG_MOUNT_ERROR,
            ErrorCodes.CONFIG_BIND_ERROR,
        ):
            return {"code": _CODE_INTERNAL_ERROR, "message": "Configuration error"}

        # Unknown apcore error code
        return {"code": _CODE_INTERNAL_ERROR, "message": "Internal server error"}

    def _refusal_message(self, error: Exception, error_code: str) -> str:
        """Caller-facing message for a governance refusal.

        Default: the fixed per-class string. With ``disclose_refusal_reason``
        (srs FR-ERR-011): apcore's own message, through the same sanitizer every
        other forwarded message goes through. An empty or whitespace-only apcore
        message falls back to the fixed string rather than sending the caller
        nothing.
        """
        fixed = _GOVERNANCE_REFUSALS[error_code]
        if not self._disclose_refusal_reason:
            return fixed
        disclosed = sanitize_message(getattr(error, "message", str(error)))
        return disclosed if disclosed.strip() else fixed

    def _sanitize_message(self, message: str) -> str:
        """Strip file paths, traceback lines, and truncate to 500 characters."""
        return sanitize_message(message)


# Direction labels apcore puts at the front of a SCHEMA_VALIDATION_ERROR message.
#
# apcore-python raises the code for input and output validation
# (``builtin_steps.py``: ``f"Input validation failed: {errors}"`` and
# ``f"Output validation failed: {errors}"``). Config validation is *not* in this
# set: apcore-python raises ``ConfigError`` / ``CONFIG_INVALID`` for it, which
# ``_handle_apcore_error`` already sends to the fixed internal string through
# its catch-all. That is the one place this differs from the Rust binding, whose
# apcore raises SCHEMA_VALIDATION_ERROR for all three directions and therefore
# matches a "Config" label too.
_SERVER_SIDE_SCHEMA_PREFIXES: tuple[str, ...] = ("Output validation failed",)


def is_server_side_schema_error(message: str) -> bool:
    """Whether a ``SCHEMA_VALIDATION_ERROR`` is about something the *server* produced.

    Reporting an output-validation failure as ``-32602 Invalid params`` tells the
    caller to fix a request that was correct, and the default ``ai_guidance``
    apcore attaches to ``SchemaValidationError`` says "Input validation failed"
    and points at a ``details.errors`` field an A2A caller never receives. Those
    are server-side defects and belong behind the fixed internal string.

    The direction label apcore puts at the front of the message is the only
    signal that exists, so this matches that prefix. Anything unrecognized keeps
    the caller-facing detail — including a module that raises the code itself
    with its own wording, whose message srs FR-ERR-002 requires the caller to
    see. Failing to recognize a server-side error therefore preserves the
    previous behaviour; it never masks a caller-fixable one by mistake.
    """
    return message.startswith(_SERVER_SIDE_SCHEMA_PREFIXES)


def carries_caller_detail(error: Exception, disclose_refusal_reason: bool = False) -> bool:
    """Whether :meth:`ErrorMapper.to_jsonrpc_error` forwards this error's own message.

    This is the partition that decides whether a message may be *widened* — with
    ``ai_guidance``, or anything else. It is deliberately not ``user_fixable``,
    which is a different partition: six apcore codes carry ``user_fixable=True``
    while falling into ``_handle_apcore_error``'s catch-all
    (``VERSION_CONSTRAINT_INVALID``, ``BINDING_SCHEMA_INFERENCE_FAILED``,
    ``BINDING_SCHEMA_MODE_CONFLICT``, ``BINDING_STRICT_SCHEMA_INCOMPATIBLE``,
    ``DEPENDENCY_NOT_FOUND``, ``DEPENDENCY_VERSION_MISMATCH``), and appending
    guidance to those would extend the fixed "Internal server error" string with
    internal detail that :func:`sanitize_message` does not strip (module ids,
    versions, env-var names, hostnames). ``user_fixable`` is also settable
    per-error by the module author, which would let any module widen any fixed
    per-class string at will, including the ``ACL_DENIED`` mask.

    The three governance codes (``ACL_DENIED``, ``APPROVAL_DENIED``,
    ``APPROVAL_TIMEOUT``) are in this partition only when
    ``disclose_refusal_reason`` is set — the same flag the mapper branches on, so
    the two surfaces agree under either setting.

    ``test_error_mapper_message_policy_matches_to_jsonrpc_error`` locks this to
    the branching in :meth:`ErrorMapper._handle_apcore_error` across every apcore
    error code and both flag values, so the two cannot drift.
    """
    error_code = getattr(error, "code", None)
    if error_code in (ErrorCodes.MODULE_NOT_FOUND, ErrorCodes.GENERAL_INVALID_INPUT):
        return True
    if error_code == ErrorCodes.SCHEMA_VALIDATION_ERROR:
        return not is_server_side_schema_error(getattr(error, "message", str(error)))
    # The three governance codes move into and out of this partition with the
    # flag, so the task-status surface forwards exactly what the JSON-RPC surface
    # does under either setting (srs FR-ERR-011 criterion 4).
    if error_code in _GOVERNANCE_REFUSALS:
        return disclose_refusal_reason
    return False


def sanitize_message(message: str) -> str:
    """Strip file paths, traceback lines, and truncate to 500 characters.

    Module-level so the task-status surface (``server.executor``) applies exactly
    the same redaction as the JSON-RPC surface.
    """
    # Match Unix absolute paths (single or multi-component) and ~ paths
    message = re.sub(r"~?/[^\s]*", "", message)
    # Strip traceback lines
    message = re.sub(r"(?m)^.*(?:Traceback|File \"|line \d+).*$", "", message)
    # Collapse internal whitespace (kept in sync with the TypeScript binding)
    message = re.sub(r"\s+", " ", message).strip()
    return message[:500]
