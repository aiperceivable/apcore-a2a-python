"""Conformance — Algorithm A-SKILL: missing/invalid skillId & unparseable parts.

Fixture: ``conformance/fixtures/skill_resolution.json`` (shared verbatim with the
TypeScript and Rust runners). Drives :class:`ApCoreAgentExecutor` with each
``params`` payload and asserts the task reaches TASK_STATE_FAILED with the
documented message. The dispatch-level ``error_cases`` (missing message
envelope) are not executor-observable and are skipped here (covered by the
per-SDK JSON-RPC server tests).
"""

from __future__ import annotations

from typing import Any

import pytest
from apcore_a2a.adapters.errors import ErrorMapper
from apcore_a2a.adapters.parts import PartConverter
from apcore_a2a.adapters.schema import SchemaConverter
from apcore_a2a.server.executor import ApCoreAgentExecutor

from . import _server
from ._spec import load_fixture

_FIXTURE = load_fixture("skill_resolution.json")


@pytest.mark.parametrize(
    "case",
    _FIXTURE["test_cases"],
    ids=[c["id"] for c in _FIXTURE["test_cases"]],
)
async def test_skill_resolution_failed_task(case: dict[str, Any]) -> None:
    # known set deliberately excludes "does.not.exist" so the unknown-skill case
    # fails closed; it includes math.add for the unparseable-parts case.
    input_schema = (case.get("skill") or {}).get("input_schema", {"type": "object"})
    executor = ApCoreAgentExecutor(
        _server.single_executor(),
        PartConverter(SchemaConverter()),
        ErrorMapper(),
        _server.registry_with(["math.add"], input_schema),
        execution_timeout=5,
    )
    ctx = _server.context_from_params(case["params"])
    queue = await _server.make_queue()
    await executor.execute(ctx, queue)

    events = [_server.classify(e) for e in await _server.drain_queue(queue)]
    failed = [f for kind, f in events if kind == "statusUpdate" and f["state"] == case["expected_task_state"]]
    assert failed, f"[{case['id']}] no {case['expected_task_state']} status; got {events}"
    message = failed[0]["message"]
    for needle in case.get("expected_status_message", []):
        assert needle in message, f"[{case['id']}] missing {needle!r} in {message!r}"
