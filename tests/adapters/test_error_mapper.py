"""Tests for ErrorMapper."""
import asyncio
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
    result = mapper.to_jsonrpc_error(asyncio.TimeoutError())
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


def test_sanitize_message_strips_paths(mapper):
    result = mapper._sanitize_message("Error at /usr/local/lib/python3.12/something.py")
    assert "/usr/local/lib/python3.12/something.py" not in result


def test_sanitize_message_truncates(mapper):
    long_msg = "x" * 600
    result = mapper._sanitize_message(long_msg)
    assert len(result) <= 500


