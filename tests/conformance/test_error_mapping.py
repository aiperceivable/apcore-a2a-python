"""Conformance — Algorithm A-ERR: apcore exception -> JSON-RPC error parity.

Fixture: ``conformance/fixtures/error_mapping.json`` (shared verbatim with the
TypeScript and Rust runners). Drives :meth:`ErrorMapper.to_jsonrpc_error` with a
reconstructed apcore exception and asserts the code plus message contains/excludes
substrings (the sanitization invariant).
"""

from __future__ import annotations

from typing import Any

import pytest
from apcore.errors import ErrorCodes, ModuleError

from apcore_a2a.adapters.errors import ErrorMapper

from ._spec import load_fixture

_FIXTURE = load_fixture("error_mapping.json")

_CODE_BY_NAME = {
    "ModuleNotFoundError": ErrorCodes.MODULE_NOT_FOUND,
    "SchemaValidationError": ErrorCodes.SCHEMA_VALIDATION_ERROR,
    "ACLDeniedError": ErrorCodes.ACL_DENIED,
    "ModuleExecuteError": ErrorCodes.MODULE_EXECUTE_ERROR,
}


def _build_exception(spec: dict[str, Any]) -> Exception:
    name = spec["exception"]
    if name == "RuntimeError":
        # An exception with no apcore .code -> the mapper's catch-all arm.
        return RuntimeError(spec.get("message", "boom"))
    if name == "SchemaValidationError":
        errors = spec.get("errors", {})
        message = "; ".join(f"{k}: {v}" for k, v in errors.items()) or "validation failed"
    elif name == "ACLDeniedError":
        # The mapper masks this; the caller/module must NOT survive into the message.
        message = f"caller {spec.get('caller')} denied access to {spec.get('module')}"
    else:
        message = spec.get("message", "")
    return ModuleError(_CODE_BY_NAME[name], message)


@pytest.mark.parametrize(
    "case",
    _FIXTURE["error_cases"],
    ids=[c["id"] for c in _FIXTURE["error_cases"]],
)
def test_error_mapping(case: dict[str, Any]) -> None:
    rpc = ErrorMapper().to_jsonrpc_error(_build_exception(case["input"]))
    assert rpc["code"] == case["expected_error_code"], f"[{case['id']}] code: got {rpc}"
    for needle in case.get("expected_error_message", []):
        assert needle in rpc["message"], f"[{case['id']}] missing {needle!r} in {rpc['message']!r}"
    for forbidden in case.get("expected_message_excludes", []):
        assert forbidden not in rpc["message"], f"[{case['id']}] leaked {forbidden!r} in {rpc['message']!r}"
