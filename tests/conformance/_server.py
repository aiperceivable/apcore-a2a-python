"""Server-level helpers for the A-SKILL / A-STREAM conformance runners.

These drive :class:`ApCoreAgentExecutor` (the unit that emits A2A events in the
Python/TS SDKs) with a stub apcore executor and collect the resulting event
stream. Kept separate from ``_spec`` because it imports a2a-sdk types.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from a2a.server.events import EventQueue
from a2a.server.events.in_memory_queue_manager import InMemoryQueueManager
from a2a.types import Message, Part, Role, TaskState
from google.protobuf import struct_pb2
from google.protobuf.json_format import ParseDict

TASK_ID = "task-1"


class CodedError(Exception):
    """Exception carrying an apcore-style ``.code`` (drives the executor arms)."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message)
        self.code = code


def build_part(spec: dict[str, Any]) -> Part:
    if "text" in spec:
        return Part(text=spec["text"])
    if "data" in spec:
        return Part(data=ParseDict(spec["data"], struct_pb2.Value()))
    if "url" in spec:
        return Part(url=spec["url"])
    raise AssertionError(f"unrecognized part spec: {spec}")


def context_from_params(params: dict[str, Any], task_id: str = TASK_ID) -> Any:
    msg_spec = params["message"]
    message = Message(
        role=Role.ROLE_USER,
        parts=[build_part(p) for p in msg_spec.get("parts", [])],
        message_id=msg_spec.get("messageId", "m1"),
    )
    # skillId lives in params.metadata (sibling of message) on the A2A wire; fall
    # back to message.metadata. The Python/TS executor reads context.message.metadata,
    # so map it there.
    meta = params.get("metadata") or msg_spec.get("metadata")
    if meta:
        message.metadata.update(meta)
    ctx = MagicMock()
    ctx.task_id = task_id
    ctx.context_id = "ctx-1"
    ctx.message = message
    return ctx


def registry_with(known: list[str], input_schema: dict[str, Any] | None = None) -> Any:
    descriptor = MagicMock(
        module_id=known[0] if known else "",
        description="conformance stub",
        input_schema=input_schema or {"type": "object"},
        output_schema={"type": "object"},
    )
    reg = MagicMock()
    reg.list.return_value = list(known)
    reg.get_definition.return_value = descriptor
    return reg


def single_executor(result: Any = None) -> Any:
    from unittest.mock import AsyncMock

    ex = MagicMock()
    ex.call_async = AsyncMock(return_value=result or {})
    # Ensure no async-gen `stream` attribute so the non-streaming path is taken.
    if hasattr(ex, "stream"):
        del ex.stream
    return ex


def streaming_executor(chunks: list[Any] | None = None, error: Exception | None = None) -> Any:
    """A stub whose ``stream`` is a real async generator (so the executor's
    ``isasyncgenfunction`` check selects the streaming path)."""

    class _Stub:
        async def call_async(self, skill_id: str, inputs: Any, *args: Any) -> Any:
            return {}

        async def stream(self, skill_id: str, inputs: Any, *args: Any):
            if error is not None:
                raise error
            for chunk in chunks or []:
                yield chunk

    return _Stub()


async def make_queue(task_id: str = TASK_ID) -> EventQueue:
    mgr = InMemoryQueueManager()
    await mgr.create_or_tap(task_id)
    return await mgr.get(task_id)


async def drain_queue(queue: EventQueue) -> list[Any]:
    import asyncio

    events: list[Any] = []
    while True:
        try:
            event = await asyncio.wait_for(queue.dequeue_event(), timeout=0.5)
        except TimeoutError:
            break
        if event is None:
            break
        events.append(event)
    return events


def classify(event: Any) -> tuple[str, dict[str, Any]]:
    """Map an a2a event object to (kind, fields) for fixture matching."""
    name = type(event).__name__
    if name == "Task":
        return "task", {"state": TaskState.Name(event.status.state)}
    if name == "TaskArtifactUpdateEvent":
        parts = list(event.artifact.parts)
        return "artifactUpdate", {
            "append": bool(event.append),
            "lastChunk": bool(event.last_chunk),
            "empty_parts": len(parts) == 0,
        }
    if name == "TaskStatusUpdateEvent":
        message = ""
        if event.status.message and event.status.message.parts:
            message = event.status.message.parts[0].text
        return "statusUpdate", {"state": TaskState.Name(event.status.state), "message": message}
    return name, {}
