"""Conformance — Algorithm A-STREAM: streaming event-sequence parity.

Fixture: ``conformance/fixtures/streaming_events.json`` (shared verbatim with the
TypeScript and Rust runners). Drives :class:`ApCoreAgentExecutor` with a stub
streaming executor and matches the collected events in order against
``expected_events``.
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

_FIXTURE = load_fixture("streaming_events.json")

_ERROR_BY_NAME = {
    "ModuleExecuteError": lambda spec: _server.CodedError("MODULE_EXECUTE_ERROR", spec.get("message", "boom")),
    "ModuleTimeoutError": lambda spec: _server.CodedError("MODULE_TIMEOUT", spec.get("message", "timeout")),
}


def _build_executor(case: dict[str, Any]):
    if "module_error" in case:
        spec = case["module_error"]
        return _server.streaming_executor(error=_ERROR_BY_NAME[spec["exception"]](spec))
    return _server.streaming_executor(chunks=case.get("module_chunks", []))


@pytest.mark.parametrize(
    "case",
    _FIXTURE["test_cases"],
    ids=[c["id"] for c in _FIXTURE["test_cases"]],
)
async def test_streaming_events(case: dict[str, Any]) -> None:
    skill_id = case["params"]["metadata"]["skillId"]
    executor = ApCoreAgentExecutor(
        _build_executor(case),
        PartConverter(SchemaConverter()),
        ErrorMapper(),
        _server.registry_with([skill_id]),
        execution_timeout=5,
    )
    ctx = _server.context_from_params(case["params"])
    queue = await _server.make_queue()
    await executor.execute(ctx, queue)

    events = [_server.classify(e) for e in await _server.drain_queue(queue)]

    # Start state (carried by the initial `task` event in Python/TS).
    if "expected_start_state" in case:
        start_states = [f["state"] for k, f in events if k in ("task", "statusUpdate")]
        assert case["expected_start_state"] in start_states, f"[{case['id']}] start state; got {events}"

    artifact_updates = [f for k, f in events if k == "artifactUpdate"]
    markers = [f for f in artifact_updates if f["lastChunk"]]
    non_marker = [f for f in artifact_updates if not f["lastChunk"]]

    if "expected_min_artifact_updates" in case:
        assert len(non_marker) >= case["expected_min_artifact_updates"], f"[{case['id']}] artifact count: {events}"

    if case.get("expected_terminal_marker"):
        assert markers and markers[-1]["empty_parts"], f"[{case['id']}] missing terminal empty-parts marker"
    elif case.get("expected_terminal_marker") is False:
        assert not markers, f"[{case['id']}] unexpected lastChunk marker"

    final_states = [f["state"] for k, f in events if k == "statusUpdate"]
    assert final_states and final_states[-1] == case["expected_final_state"], f"[{case['id']}] final state: {events}"

    if "expected_status_message" in case or "expected_status_message_excludes" in case:
        failed = [f for k, f in events if k == "statusUpdate" and f["state"] == "TASK_STATE_FAILED"]
        assert failed, f"[{case['id']}] no FAILED status"
        message = failed[0]["message"]
        for needle in case.get("expected_status_message", []):
            assert needle in message, f"[{case['id']}] missing {needle!r} in {message!r}"
        for forbidden in case.get("expected_status_message_excludes", []):
            assert forbidden not in message, f"[{case['id']}] leaked {forbidden!r} in {message!r}"
