"""Tests for ErrorMapper."""

import pytest

from apcore_a2a.adapters.errors import ErrorMapper


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
