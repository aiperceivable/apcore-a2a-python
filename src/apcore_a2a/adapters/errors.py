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
_CODE_TASK_NOT_FOUND = -32001  # ACL denied (masked as "not found")


class ErrorMapper:
    """Maps apcore exceptions to A2A JSON-RPC error dicts.

    Security note: ACL errors are masked; internal errors never expose
    file paths, caller identity, or stack traces to the caller.
    """

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

        if error_code == ErrorCodes.ACL_DENIED:
            # Mask: don't reveal that the resource exists, user identity, etc.
            return {"code": _CODE_TASK_NOT_FOUND, "message": "Task not found"}

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


def carries_caller_detail(error: Exception) -> bool:
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

    ``test_error_mapper_message_policy_matches_to_jsonrpc_error`` locks this to
    the branching in :meth:`ErrorMapper._handle_apcore_error` across every apcore
    error code, so the two cannot drift.
    """
    error_code = getattr(error, "code", None)
    if error_code in (ErrorCodes.MODULE_NOT_FOUND, ErrorCodes.GENERAL_INVALID_INPUT):
        return True
    if error_code == ErrorCodes.SCHEMA_VALIDATION_ERROR:
        return not is_server_side_schema_error(getattr(error, "message", str(error)))
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
