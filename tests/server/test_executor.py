"""Tests for ApCoreAgentExecutor."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from a2a.server.events import EventQueue
from a2a.server.events.in_memory_queue_manager import InMemoryQueueManager
from a2a.types import Message, Part, Role, TaskState, TaskStatusUpdateEvent, TextPart

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
    ctx.message = Message(
        role=Role.user,
        parts=[Part(root=TextPart(text=text))],
        message_id="msg-1",
        metadata={"skillId": skill_id},
    )
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
        except asyncio.TimeoutError:
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
    assert any(e.status.state == TaskState.completed for e in status_events)


async def test_execute_missing_skill_id_enqueues_failed(apcore_executor):
    """Missing skillId in metadata → failed event."""
    ctx = MagicMock()
    ctx.task_id = "task-1"
    ctx.context_id = "ctx-1"
    ctx.message = Message(
        role=Role.user,
        parts=[Part(root=TextPart(text="hi"))],
        message_id="msg-1",
        metadata={},
    )
    queue = await _make_queue()

    await apcore_executor.execute(ctx, queue)

    events = await _drain_queue(queue)
    status_events = [e for e in events if hasattr(e, "status")]
    assert any(e.status.state == TaskState.failed for e in status_events)
    msg = status_events[0].status.message.parts[0].root.text
    assert "skillId" in msg


async def test_execute_unknown_skill_enqueues_failed(apcore_executor):
    """Unknown skill → failed event."""
    ctx = _make_context(skill_id="unknown.skill")
    queue = await _make_queue()

    await apcore_executor.execute(ctx, queue)

    events = await _drain_queue(queue)
    status_events = [e for e in events if hasattr(e, "status")]
    assert any(e.status.state == TaskState.failed for e in status_events)


async def test_execute_timeout_enqueues_failed(apcore_executor, mock_executor):
    """asyncio.TimeoutError → failed event."""
    mock_executor.call_async = AsyncMock(side_effect=asyncio.TimeoutError())
    ctx = _make_context(skill_id="image.resize", text='{"width": 800}')
    queue = await _make_queue()

    await apcore_executor.execute(ctx, queue)

    events = await _drain_queue(queue)
    status_events = [e for e in events if hasattr(e, "status")]
    assert any(e.status.state == TaskState.failed for e in status_events)


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
    assert any(e.status.state == TaskState.input_required for e in status_events)


async def test_execute_generic_exception_enqueues_failed(apcore_executor, mock_executor):
    """Generic exception → failed event (no internal details leaked)."""
    mock_executor.call_async = AsyncMock(side_effect=RuntimeError("internal secret"))
    ctx = _make_context(skill_id="image.resize", text='{"width": 800}')
    queue = await _make_queue()

    await apcore_executor.execute(ctx, queue)

    events = await _drain_queue(queue)
    status_events = [e for e in events if hasattr(e, "status")]
    assert any(e.status.state == TaskState.failed for e in status_events)
    # Error message must not leak internal details
    msg = status_events[0].status.message.parts[0].root.text
    assert "secret" not in msg.lower()


async def test_cancel_enqueues_canceled(apcore_executor):
    """cancel() enqueues canceled event."""
    ctx = _make_context()
    queue = await _make_queue()

    await apcore_executor.cancel(ctx, queue)

    events = await _drain_queue(queue)
    status_events = [e for e in events if hasattr(e, "status")]
    assert any(e.status.state == TaskState.canceled for e in status_events)


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
    ctx.message = Message(
        role=Role.user,
        parts=[Part(root=TextPart(text="hi"))],
        message_id="msg-1",
        metadata={},
    )
    queue = await _make_queue()

    await executor.execute(ctx, queue)

    assert ("submitted", "failed") in calls


async def test_on_state_change_called_on_timeout(mock_executor, mock_registry):
    """T1: on_state_change receives (working→failed) on timeout."""
    mock_executor.call_async = AsyncMock(side_effect=asyncio.TimeoutError())
    calls: list[tuple[str, str]] = []
    executor = ApCoreAgentExecutor(
        mock_executor,
        PartConverter(SchemaConverter()),
        ErrorMapper(),
        mock_registry,
        execution_timeout=5,
        on_state_change=lambda old, new: calls.append((old, new)),
    )
    ctx = _make_context(skill_id="image.resize", text='{}')
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
    ctx = _make_context(skill_id="image.resize", text='{}')
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
    ctx = _make_context(skill_id="image.resize", text='{}')
    queue = await _make_queue()
    # Must not raise
    await executor.execute(ctx, queue)
