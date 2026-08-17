"""Tests for ApCoreAgentExecutor."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from a2a.server.events import EventQueue
from a2a.server.events.in_memory_queue_manager import InMemoryQueueManager
from a2a.types import Message, Part, Role, TaskState
from apcore.errors import ErrorCodes, ModuleError

from apcore_a2a.adapters.errors import ErrorMapper
from apcore_a2a.adapters.parts import PartConverter
from apcore_a2a.adapters.schema import SchemaConverter
from apcore_a2a.server.executor import ApCoreAgentExecutor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(skill_id: str = "image.resize", text: str = "hello", task_id: str = "task-1"):
    ctx = MagicMock()
    ctx.task_id = task_id
    ctx.context_id = "ctx-1"
    msg = Message(
        role=Role.ROLE_USER,
        parts=[Part(text=text)],
        message_id="msg-1",
    )
    msg.metadata.update({"skillId": skill_id})
    ctx.message = msg
    return ctx


async def _drain_queue(event_queue: EventQueue) -> list:
    # T2: use 0.5s timeout to avoid flakiness on slow CI runners
    events = []
    while True:
        try:
            event = await asyncio.wait_for(event_queue.dequeue_event(), timeout=0.5)
            if event is None:
                break
            events.append(event)
        except TimeoutError:
            break
    return events


async def _make_queue() -> EventQueue:
    mgr = InMemoryQueueManager()
    await mgr.create_or_tap("task-1")
    return await mgr.get("task-1")


@pytest.fixture
def mock_registry():
    reg = MagicMock()
    reg.list.return_value = ["image.resize"]
    reg.get_definition.return_value = MagicMock(
        module_id="image.resize",
        description="Resize",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
    )
    return reg


@pytest.fixture
def mock_executor():
    ex = MagicMock()
    ex.call_async = AsyncMock(return_value={"width": 800})
    return ex


@pytest.fixture
def apcore_executor(mock_executor, mock_registry):
    return ApCoreAgentExecutor(
        mock_executor,
        PartConverter(SchemaConverter()),
        ErrorMapper(),
        mock_registry,
        execution_timeout=5,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_execute_happy_path_enqueues_artifact_and_completed(apcore_executor):
    """Happy path: execute() enqueues artifact then completed event."""
    ctx = _make_context(skill_id="image.resize", text='{"width": 800}')
    queue = await _make_queue()

    await apcore_executor.execute(ctx, queue)

    events = await _drain_queue(queue)
    kinds = [type(e).__name__ for e in events]
    assert "TaskArtifactUpdateEvent" in kinds
    assert "TaskStatusUpdateEvent" in kinds

    status_events = [e for e in events if hasattr(e, "status")]
    assert any(e.status.state == TaskState.TASK_STATE_COMPLETED for e in status_events)


async def test_execute_missing_skill_id_enqueues_failed(apcore_executor):
    """Missing skillId in metadata → failed event."""
    ctx = MagicMock()
    ctx.task_id = "task-1"
    ctx.context_id = "ctx-1"
    msg = Message(
        role=Role.ROLE_USER,
        parts=[Part(text="hi")],
        message_id="msg-1",
    )
    ctx.message = msg
    queue = await _make_queue()

    await apcore_executor.execute(ctx, queue)

    events = await _drain_queue(queue)
    status_events = [e for e in events if hasattr(e, "status")]
    assert any(e.status.state == TaskState.TASK_STATE_FAILED for e in status_events)
    # Find the specific failed event (first event is now initial Task with SUBMITTED state)
    failed_events = [e for e in status_events if e.status.state == TaskState.TASK_STATE_FAILED]
    msg_text = failed_events[0].status.message.parts[0].text
    assert "skillId" in msg_text


async def test_execute_unknown_skill_enqueues_failed(apcore_executor):
    """Unknown skill → failed event."""
    ctx = _make_context(skill_id="unknown.skill")
    queue = await _make_queue()

    await apcore_executor.execute(ctx, queue)

    events = await _drain_queue(queue)
    status_events = [e for e in events if hasattr(e, "status")]
    assert any(e.status.state == TaskState.TASK_STATE_FAILED for e in status_events)


async def test_execute_timeout_enqueues_failed(apcore_executor, mock_executor):
    """asyncio.TimeoutError → failed event."""
    mock_executor.call_async = AsyncMock(side_effect=TimeoutError())
    ctx = _make_context(skill_id="image.resize", text='{"width": 800}')
    queue = await _make_queue()

    await apcore_executor.execute(ctx, queue)

    events = await _drain_queue(queue)
    status_events = [e for e in events if hasattr(e, "status")]
    assert any(e.status.state == TaskState.TASK_STATE_FAILED for e in status_events)


async def test_execute_approval_pending_enqueues_input_required(apcore_executor, mock_executor):
    """APPROVAL_PENDING code → input_required event."""

    class ApprovalError(Exception):
        code = "APPROVAL_PENDING"

    mock_executor.call_async = AsyncMock(side_effect=ApprovalError("needs approval"))
    ctx = _make_context(skill_id="image.resize", text='{"width": 800}')
    queue = await _make_queue()

    await apcore_executor.execute(ctx, queue)

    events = await _drain_queue(queue)
    status_events = [e for e in events if hasattr(e, "status")]
    assert any(e.status.state == TaskState.TASK_STATE_INPUT_REQUIRED for e in status_events)


async def test_execute_generic_exception_enqueues_failed(apcore_executor, mock_executor):
    """Generic exception → failed event (no internal details leaked)."""
    mock_executor.call_async = AsyncMock(side_effect=RuntimeError("internal secret"))
    ctx = _make_context(skill_id="image.resize", text='{"width": 800}')
    queue = await _make_queue()

    await apcore_executor.execute(ctx, queue)

    events = await _drain_queue(queue)
    status_events = [e for e in events if hasattr(e, "status")]
    assert any(e.status.state == TaskState.TASK_STATE_FAILED for e in status_events)
    # Error message must not leak internal details
    # Find the specific failed event (first event is now initial Task with SUBMITTED state)
    failed_events = [e for e in status_events if e.status.state == TaskState.TASK_STATE_FAILED]
    msg_text = failed_events[0].status.message.parts[0].text
    assert "secret" not in msg_text.lower()


async def test_cancel_enqueues_canceled(apcore_executor):
    """cancel() enqueues canceled event."""
    ctx = _make_context()
    queue = await _make_queue()

    await apcore_executor.cancel(ctx, queue)

    events = await _drain_queue(queue)
    status_events = [e for e in events if hasattr(e, "status")]
    assert any(e.status.state == TaskState.TASK_STATE_CANCELED for e in status_events)


# ---------------------------------------------------------------------------
# T1: on_state_change callback tests
# ---------------------------------------------------------------------------


async def test_on_state_change_called_on_success(mock_executor, mock_registry):
    """T1: on_state_change receives (submitted→working) then (working→completed) on success."""
    calls: list[tuple[str, str]] = []
    executor = ApCoreAgentExecutor(
        mock_executor,
        PartConverter(SchemaConverter()),
        ErrorMapper(),
        mock_registry,
        execution_timeout=5,
        on_state_change=lambda old, new: calls.append((old, new)),
    )
    ctx = _make_context(skill_id="image.resize", text='{"width": 800}')
    queue = await _make_queue()

    await executor.execute(ctx, queue)

    assert ("submitted", "working") in calls
    assert ("working", "completed") in calls


async def test_on_state_change_called_on_missing_skill_id(mock_executor, mock_registry):
    """T1: on_state_change receives (submitted→failed) when skillId is missing."""
    calls: list[tuple[str, str]] = []
    executor = ApCoreAgentExecutor(
        mock_executor,
        PartConverter(SchemaConverter()),
        ErrorMapper(),
        mock_registry,
        execution_timeout=5,
        on_state_change=lambda old, new: calls.append((old, new)),
    )
    ctx = MagicMock()
    ctx.task_id = "task-1"
    ctx.context_id = "ctx-1"
    msg = Message(
        role=Role.ROLE_USER,
        parts=[Part(text="hi")],
        message_id="msg-1",
    )
    ctx.message = msg
    queue = await _make_queue()

    await executor.execute(ctx, queue)

    assert ("submitted", "failed") in calls


async def test_on_state_change_called_on_timeout(mock_executor, mock_registry):
    """T1: on_state_change receives (working→failed) on timeout."""
    mock_executor.call_async = AsyncMock(side_effect=TimeoutError())
    calls: list[tuple[str, str]] = []
    executor = ApCoreAgentExecutor(
        mock_executor,
        PartConverter(SchemaConverter()),
        ErrorMapper(),
        mock_registry,
        execution_timeout=5,
        on_state_change=lambda old, new: calls.append((old, new)),
    )
    ctx = _make_context(skill_id="image.resize", text="{}")
    queue = await _make_queue()

    await executor.execute(ctx, queue)

    assert ("working", "failed") in calls


async def test_on_state_change_called_on_approval_pending(mock_executor, mock_registry):
    """T1: on_state_change receives (working→input_required) on APPROVAL_PENDING."""

    class ApprovalError(Exception):
        code = "APPROVAL_PENDING"

    mock_executor.call_async = AsyncMock(side_effect=ApprovalError("needs approval"))
    calls: list[tuple[str, str]] = []
    executor = ApCoreAgentExecutor(
        mock_executor,
        PartConverter(SchemaConverter()),
        ErrorMapper(),
        mock_registry,
        execution_timeout=5,
        on_state_change=lambda old, new: calls.append((old, new)),
    )
    ctx = _make_context(skill_id="image.resize", text="{}")
    queue = await _make_queue()

    await executor.execute(ctx, queue)

    assert ("working", "input_required") in calls


async def test_on_state_change_not_called_when_none(mock_executor, mock_registry):
    """T1: no error when on_state_change is None (default)."""
    executor = ApCoreAgentExecutor(
        mock_executor,
        PartConverter(SchemaConverter()),
        ErrorMapper(),
        mock_registry,
        execution_timeout=5,
        # on_state_change defaults to None
    )
    ctx = _make_context(skill_id="image.resize", text="{}")
    queue = await _make_queue()
    # Must not raise
    await executor.execute(ctx, queue)


async def test_execute_streams_even_when_apcore_ctx_is_none(mock_registry, monkeypatch):
    """A-D-016: a streaming executor must be dispatched to the streaming path
    even in the degraded no-apcore-binding state (apcore_ctx is None),
    matching TS canStream (which checks only the stream method) and
    executeStreaming (which tolerates a null ctx).
    """
    # Force apcore_ctx to remain None by making Context.create raise, so the
    # executor's `except: pass` leaves apcore_ctx = None.
    import apcore

    monkeypatch.setattr(apcore.Context, "create", MagicMock(side_effect=RuntimeError("no binding")))

    received_args: list = []

    class _StreamingExecutor:
        async def stream(self, module_id, inputs, ctx=None):
            # Record positional args to assert the ctx was NOT passed.
            received_args.append((module_id, inputs, ctx))
            yield {"chunk": 1}
            yield {"chunk": 2}

    executor = ApCoreAgentExecutor(
        _StreamingExecutor(),
        PartConverter(SchemaConverter()),
        ErrorMapper(),
        mock_registry,
        execution_timeout=5,
    )
    ctx = _make_context(skill_id="image.resize", text="{}")
    queue = await _make_queue()

    await executor.execute(ctx, queue)

    # Streaming path was taken: stream() was invoked without the apcore ctx.
    assert len(received_args) == 1
    assert received_args[0][2] is None

    events = await _drain_queue(queue)
    artifact_events = [e for e in events if type(e).__name__ == "TaskArtifactUpdateEvent"]
    # Two chunk artifacts + a final last_chunk artifact.
    assert len(artifact_events) >= 2
    status_events = [e for e in events if hasattr(e, "status")]
    assert any(e.status.state == TaskState.TASK_STATE_COMPLETED for e in status_events)


# ---------------------------------------------------------------------------
# Failed-task error classification (apexe #33)
# ---------------------------------------------------------------------------


async def _failed_text(apcore_executor, mock_executor, error: Exception) -> str:
    """Run one failing execution and return the FAILED status message text."""
    mock_executor.call_async = AsyncMock(side_effect=error)
    ctx = _make_context(skill_id="image.resize", text='{"width": 800}')
    queue = await _make_queue()
    await apcore_executor.execute(ctx, queue)
    events = await _drain_queue(queue)
    failed = [e for e in events if hasattr(e, "status") and e.status.state == TaskState.TASK_STATE_FAILED]
    assert failed, "expected a FAILED status event"
    return failed[0].status.message.parts[0].text


async def test_execute_invalid_input_error_reaches_the_caller(apcore_executor, mock_executor):
    """srs FR-ERR-002/FR-ERR-006: a caller-fixable failure must carry detail.

    Collapsing it to the generic string leaves an agent unable to tell a bad
    argument from a crash, which is the whole point of the transport.
    """
    err = ModuleError(
        code=ErrorCodes.GENERAL_INVALID_INPUT,
        message="Parameters '1' and 'l' cannot be used together",
    )
    text = await _failed_text(apcore_executor, mock_executor, err)
    assert "'1' and 'l' cannot be used together" in text


async def test_execute_schema_validation_error_names_the_field(apcore_executor, mock_executor):
    err = ModuleError(code=ErrorCodes.SCHEMA_VALIDATION_ERROR, message="width: must be integer")
    text = await _failed_text(apcore_executor, mock_executor, err)
    assert "width" in text


async def test_execute_acl_denied_stays_masked_as_task_not_found(apcore_executor, mock_executor):
    """srs FR-ERR-003: an ACL denial must not disclose caller, module or denial."""
    err = ModuleError(code=ErrorCodes.ACL_DENIED, message="caller alice denied module admin.wipe")
    text = await _failed_text(apcore_executor, mock_executor, err)
    assert text == "Task not found"
    assert "alice" not in text
    assert "admin.wipe" not in text


async def test_execute_internal_error_yields_fixed_message(apcore_executor, mock_executor):
    """srs FR-ERR-004 / FR-ERR-008: internal and unrecognized errors stay fixed."""
    err = ModuleError(
        code=ErrorCodes.GENERAL_INTERNAL_ERROR,
        message="super secret internal detail leaking through",
    )
    text = await _failed_text(apcore_executor, mock_executor, err)
    assert text == "Internal server error"


async def test_execute_ai_guidance_is_appended_for_caller_fixable_errors(apcore_executor, mock_executor):
    """ai_guidance exists to tell an agent what to do next; the caller sees only this."""
    err = ModuleError(
        code=ErrorCodes.GENERAL_INVALID_INPUT,
        message="bad flag combination",
        ai_guidance="send either -1 or -l, not both",
    )
    text = await _failed_text(apcore_executor, mock_executor, err)
    assert "send either -1 or -l, not both" in text


async def test_execute_ai_guidance_is_withheld_for_internal_errors(apcore_executor, mock_executor):
    """The fixed per-class strings must stay fixed.

    ``DEPENDENCY_NOT_FOUND`` is the case that discriminates: apcore marks it
    ``user_fixable=True`` while the mapper sends it through the catch-all to
    "Internal server error", so a ``user_fixable``-based gate would append the
    guidance verbatim — internal dependency-graph detail (module ids, versions,
    env-var names, hostnames), none of which ``sanitize_message`` strips.
    """
    err = ModuleError(
        code=ErrorCodes.DEPENDENCY_NOT_FOUND,
        message="boom",
        ai_guidance="module 'billing.charge' requires 'vault.secrets' >= 2.1; set VAULT_ADDR",
    )
    assert err.user_fixable is True, "precondition for this test"
    text = await _failed_text(apcore_executor, mock_executor, err)
    assert text == "Internal server error"

    internal = ModuleError(
        code=ErrorCodes.GENERAL_INTERNAL_ERROR,
        message="boom",
        ai_guidance="inspect /var/log/secret.log",
    )
    assert await _failed_text(apcore_executor, mock_executor, internal) == "Internal server error"


async def test_execute_ai_guidance_is_withheld_when_a_module_declares_a_masked_error_user_fixable(
    apcore_executor, mock_executor
):
    """``user_fixable`` is author-settable, so gating on it let any module widen a fixed string."""
    err = ModuleError(
        code=ErrorCodes.ACL_DENIED,
        message="caller alice denied admin.wipe",
        user_fixable=True,
        ai_guidance="ask an admin to grant you the 'admin.wipe' role",
    )
    text = await _failed_text(apcore_executor, mock_executor, err)
    assert text == "Task not found"


async def test_execute_failure_text_does_not_leak_paths_or_tracebacks(apcore_executor, mock_executor):
    """The redaction that the fixed string used to provide must survive the fix."""
    err = ModuleError(
        code=ErrorCodes.GENERAL_INVALID_INPUT,
        message='bad input at /home/deploy/app/secret.py\nTraceback (most recent call last):\nFile "x.py", line 42',
        ai_guidance="see /var/log/apcore/internal.log on db-prod-07",
    )
    text = await _failed_text(apcore_executor, mock_executor, err)
    assert "/home/deploy" not in text
    assert "/var/log" not in text
    assert "Traceback" not in text
    assert "line 42" not in text
