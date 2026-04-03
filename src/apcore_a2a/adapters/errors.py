"""ErrorMapper: maps apcore exceptions to A2A JSON-RPC error dicts."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

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
        if error_code == "MODULE_NOT_FOUND":
            # Extract module ID from message if possible
            message = self._sanitize_message(getattr(error, "message", str(error)))
            return {"code": _CODE_METHOD_NOT_FOUND, "message": message}

        if error_code == "SCHEMA_VALIDATION_ERROR":
            message = self._sanitize_message(getattr(error, "message", str(error)))
            return {"code": _CODE_INVALID_PARAMS, "message": message}

        if error_code == "ACL_DENIED":
            # Mask: don't reveal that the resource exists, user identity, etc.
            return {"code": _CODE_TASK_NOT_FOUND, "message": "Task not found"}

        if error_code in ("MODULE_TIMEOUT", "EXECUTION_TIMEOUT"):
            return {"code": _CODE_INTERNAL_ERROR, "message": "Execution timeout"}

        if error_code in (
            "CALL_DEPTH_EXCEEDED",
            "CIRCULAR_CALL",
            "CALL_FREQUENCY_EXCEEDED",
        ):
            return {"code": _CODE_INTERNAL_ERROR, "message": "Safety limit exceeded"}

        if error_code == "MODULE_DISABLED":
            return {"code": _CODE_INTERNAL_ERROR, "message": "Module is currently disabled"}

        if error_code in ("CONFIG_NAMESPACE_DUPLICATE", "CONFIG_MOUNT_ERROR", "CONFIG_BIND_ERROR"):
            return {"code": _CODE_INTERNAL_ERROR, "message": "Configuration error"}

        if error_code == "INVALID_INPUT":
            description = self._sanitize_message(getattr(error, "message", str(error)))
            return {"code": _CODE_INVALID_PARAMS, "message": f"Invalid input: {description}"}

        # Unknown apcore error code
        return {"code": _CODE_INTERNAL_ERROR, "message": "Internal server error"}

    def _sanitize_message(self, message: str) -> str:
        """Strip file paths, traceback lines, and truncate to 500 characters."""
        # Match Unix absolute paths (single or multi-component) and ~ paths
        message = re.sub(r"~?/[^\s]*", "", message)
        # Strip traceback lines
        message = re.sub(r"(?m)^.*(?:Traceback|File \"|line \d+).*$", "", message)
        message = message.strip()
        return message[:500]
