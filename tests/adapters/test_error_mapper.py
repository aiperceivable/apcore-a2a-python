"""Tests for ErrorMapper."""

import pytest
from apcore.errors import ErrorCodes, ModuleError, SchemaValidationError

from apcore_a2a.adapters.errors import (
    ErrorMapper,
    carries_caller_detail,
    is_server_side_schema_error,
)


@pytest.fixture
def mapper():
    return ErrorMapper()


class FakeApCoreError(Exception):
    def __init__(self, code: str, message: str, details=None):
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)


def test_generic_exception(mapper):
    result = mapper.to_jsonrpc_error(ValueError("oops"))
    assert result["code"] == -32603
    assert "internal" in result["message"].lower() or "error" in result["message"].lower()


def test_timeout_error(mapper):
    result = mapper.to_jsonrpc_error(TimeoutError())
    assert result["code"] == -32603
    assert "timeout" in result["message"].lower()


def test_module_not_found_error(mapper):
    err = FakeApCoreError("MODULE_NOT_FOUND", "Module not found: image.resize")
    result = mapper.to_jsonrpc_error(err)
    assert result["code"] == -32601


def test_schema_validation_error(mapper):
    err = FakeApCoreError("SCHEMA_VALIDATION_ERROR", "Validation failed")
    result = mapper.to_jsonrpc_error(err)
    assert result["code"] == -32602


def test_acl_denied_masked(mapper):
    err = FakeApCoreError("ACL_DENIED", "Access denied for user: alice")
    result = mapper.to_jsonrpc_error(err)
    assert result["code"] == -32001
    # Message should NOT reveal user or module info
    assert "alice" not in result["message"]
    assert "alice" not in str(result.get("data", ""))


def test_unknown_apcore_error(mapper):
    err = FakeApCoreError("SOME_OTHER_ERROR", "Some error")
    result = mapper.to_jsonrpc_error(err)
    assert result["code"] == -32603


def test_result_has_code_and_message(mapper):
    result = mapper.to_jsonrpc_error(RuntimeError("test"))
    assert "code" in result
    assert "message" in result


def test_module_disabled_error(mapper):
    err = FakeApCoreError("MODULE_DISABLED", "Module foo is disabled")
    result = mapper.to_jsonrpc_error(err)
    assert result["code"] == -32603
    assert result["message"] == "Module is currently disabled"


def test_config_namespace_duplicate_error(mapper):
    err = FakeApCoreError("CONFIG_NAMESPACE_DUPLICATE", "Namespace already registered")
    result = mapper.to_jsonrpc_error(err)
    assert result["code"] == -32603
    assert result["message"] == "Configuration error"


def test_config_mount_error(mapper):
    err = FakeApCoreError("CONFIG_MOUNT_ERROR", "Mount failed")
    result = mapper.to_jsonrpc_error(err)
    assert result["code"] == -32603
    assert result["message"] == "Configuration error"


def test_config_bind_error(mapper):
    err = FakeApCoreError("CONFIG_BIND_ERROR", "Bind failed")
    result = mapper.to_jsonrpc_error(err)
    assert result["code"] == -32603
    assert result["message"] == "Configuration error"


def test_format_delegates_to_to_jsonrpc_error(mapper):
    """format() method delegates to to_jsonrpc_error() for ErrorFormatter protocol."""
    err = FakeApCoreError("MODULE_NOT_FOUND", "Module not found: foo")
    result = mapper.format(err)
    assert result["code"] == -32601
    assert result == mapper.to_jsonrpc_error(err)


def test_format_accepts_context_param(mapper):
    """format() accepts an optional context parameter."""
    err = ValueError("test")
    result = mapper.format(err, context={"some": "context"})
    assert result["code"] == -32603


def test_sanitize_message_strips_paths(mapper):
    result = mapper._sanitize_message("Error at /usr/local/lib/python3.12/something.py")
    assert "/usr/local/lib/python3.12/something.py" not in result


def test_sanitize_message_truncates(mapper):
    long_msg = "x" * 600
    result = mapper._sanitize_message(long_msg)
    assert len(result) <= 500


# ---------------------------------------------------------------------------
# Message-widening policy (apexe #33)
# ---------------------------------------------------------------------------


def _all_apcore_error_codes() -> list[str]:
    """Every string constant on apcore's ErrorCodes."""
    return sorted(
        value
        for name in dir(ErrorCodes)
        if not name.startswith("_")
        for value in [getattr(ErrorCodes, name)]
        if isinstance(value, str)
    )


def test_error_mapper_message_policy_matches_to_jsonrpc_error(mapper):
    """carries_caller_detail must name exactly the codes whose message is forwarded.

    It is what gates message widening (see ``ApCoreAgentExecutor._failure_text``),
    so it has to agree with ``ErrorMapper._handle_apcore_error``'s own branching.
    Asserted over every apcore error code with a sentinel that survives
    sanitization, so adding a code or a branch cannot silently desync the two.
    """
    sentinel = "canary-2f8a"
    codes = _all_apcore_error_codes()
    assert len(codes) > 50, "sanity: ErrorCodes should expose the full apcore code set"

    for code in codes:
        err = ModuleError(code=code, message=sentinel)
        forwarded = sentinel in mapper.to_jsonrpc_error(err)["message"]
        assert forwarded == carries_caller_detail(err), (
            f"{code}: to_jsonrpc_error forwards the message = {forwarded}, "
            f"carries_caller_detail = {carries_caller_detail(err)}"
        )

    # The one code whose policy is not decided by the code alone.
    for message in ["Output validation failed: [{'field': 'width'}]", "Output validation failed"]:
        err = ModuleError(code=ErrorCodes.SCHEMA_VALIDATION_ERROR, message=message)
        assert not carries_caller_detail(err), message
        assert mapper.to_jsonrpc_error(err)["message"] == "Internal server error", message


def test_output_validation_failure_is_not_reported_as_caller_fixable(mapper):
    """apcore raises SCHEMA_VALIDATION_ERROR for output validation too.

    A module returning the wrong shape reached the caller as ``-32602 Invalid
    params`` — telling them to fix a correct request, with apcore's default
    guidance claiming "Input validation failed" and pointing at a ``details``
    field an A2A caller never receives.
    """
    err = SchemaValidationError(message="Output validation failed: [{'loc': 'width'}]")
    result = mapper.to_jsonrpc_error(err)
    assert result["code"] == -32603
    assert result["message"] == "Internal server error"

    # Input validation — the caller-fixable direction — is untouched, and so is
    # a module raising the code with its own wording.
    for message in ["Input validation failed: [{'loc': 'width'}]", "width: must be integer"]:
        result = mapper.to_jsonrpc_error(ModuleError(code=ErrorCodes.SCHEMA_VALIDATION_ERROR, message=message))
        assert result["code"] == -32602, message
        assert result["message"] == message, message


def test_is_server_side_schema_error_matches_only_the_output_direction():
    assert is_server_side_schema_error("Output validation failed: [{'loc': 'width'}]")
    assert not is_server_side_schema_error("Input validation failed: [{'loc': 'width'}]")
    # apcore-python raises ConfigError / CONFIG_INVALID for config validation,
    # which the mapper's catch-all already masks, so no "Config" label reaches
    # this function.
    assert not is_server_side_schema_error("Configuration validation failed (1 error(s)):")
    assert not is_server_side_schema_error("width: must be integer")
