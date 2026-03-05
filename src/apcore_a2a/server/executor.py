"""ApCoreAgentExecutor: bridges apcore execution to the a2a-sdk AgentExecutor ABC."""
from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import (
    Artifact,
    Message,
    Part,
    Role,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
)

# Imported at module level — no circular dependency (middleware.py does not import executor.py)
from apcore_a2a.auth.middleware import auth_identity_var

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _text_message(text: str) -> Message:
    return Message(
        role=Role.agent,
        parts=[Part(root=TextPart(text=text))],
        message_id=str(uuid4()),
    )


class ApCoreAgentExecutor(AgentExecutor):
    """Bridges apcore executor to a2a-sdk's AgentExecutor interface."""

    def __init__(
        self,
        executor: Any,
        part_converter: Any,
        error_mapper: Any,
        registry: Any = None,
        execution_timeout: int = 300,
        on_state_change: Callable[[str, str], None] | None = None,
    ) -> None:
        self._executor = executor
        self._part_converter = part_converter
        self._error_mapper = error_mapper
        self._registry = registry
        self._execution_timeout = execution_timeout
        self._on_state_change = on_state_change
        # Cache inspect.signature results keyed by stable method qualified name
        self._context_accepts_cache: dict[str, bool] = {}

    def _notify(self, old_state: str, new_state: str) -> None:
        if self._on_state_change is not None:
            try:
                self._on_state_change(old_state, new_state)
            except Exception:
                logger.debug("on_state_change callback raised", exc_info=True)

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        # 1. Get skill_id from message metadata
        metadata = (context.message.metadata or {}) if context.message else {}
        skill_id = metadata.get("skillId")
        if not skill_id:
            self._notify("submitted", "failed")
            await self._fail(context, event_queue, "Missing required parameter: metadata.skillId")
            return

        # 2. Validate skill exists in registry
        if self._registry is not None:
            try:
                known = self._registry.list()
                if skill_id not in known:
                    self._notify("submitted", "failed")
                    await self._fail(context, event_queue, f"Skill not found: {skill_id}")
                    return
            except Exception:
                pass

        # 3. Parse Parts → apcore input
        parts = context.message.parts if context.message else []
        descriptor = None
        if self._registry is not None:
            try:
                descriptor = self._registry.get_definition(skill_id)
            except Exception:
                logger.warning("Failed to get descriptor for %s", skill_id)

        try:
            inputs = self._part_converter.parts_to_input(parts, descriptor)
        except Exception as e:
            self._notify("submitted", "failed")
            await self._fail(context, event_queue, str(e))
            return

        # 4. Build apcore Identity context
        identity = auth_identity_var.get()
        apcore_ctx = None
        try:
            from apcore import Context  # type: ignore[import]
            apcore_ctx = Context.create(identity=identity) if identity else Context.create()
        except Exception:
            pass

        # 5. Execute via Executor.call_async() — task moves to working state
        self._notify("submitted", "working")
        try:
            call_async = self._executor.call_async
            cache_key = getattr(call_async, "__qualname__", repr(call_async))
            accepts_ctx = self._context_accepts_cache.get(cache_key)
            if accepts_ctx is None:
                accepts_ctx = "context" in inspect.signature(call_async).parameters
                self._context_accepts_cache[cache_key] = accepts_ctx

            coro = (
                call_async(skill_id, inputs, apcore_ctx)
                if (apcore_ctx is not None and accepts_ctx)
                else call_async(skill_id, inputs)
            )
            output = await asyncio.wait_for(coro, timeout=self._execution_timeout)
        except asyncio.TimeoutError:
            self._notify("working", "failed")
            await self._fail(context, event_queue, "Execution timed out")
            return
        except Exception as exc:
            pending_code = getattr(exc, "code", None)
            if pending_code == "APPROVAL_PENDING":
                self._notify("working", "input_required")
                await self._input_required(context, event_queue, str(exc))
            else:
                logger.exception("Execution failed for task %s skill %s", context.task_id, skill_id)
                self._notify("working", "failed")
                await self._fail(context, event_queue, "Internal server error")
            return

        # 6. Publish artifact + completed event
        artifact = self._part_converter.output_to_parts(output, context.task_id)
        context_id = context.context_id or context.task_id
        await event_queue.enqueue_event(
            TaskArtifactUpdateEvent(
                task_id=context.task_id,
                context_id=context_id,
                artifact=artifact,
                append=False,
                last_chunk=True,
            )
        )
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.completed, timestamp=_utc_now()),
                final=True,
            )
        )
        self._notify("working", "completed")

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        context_id = context.context_id or context.task_id
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context_id,
                status=TaskStatus(
                    state=TaskState.canceled,
                    timestamp=_utc_now(),
                    message=_text_message("Canceled by client"),
                ),
                final=True,
            )
        )
        self._notify("working", "canceled")

    async def _fail(
        self, context: RequestContext, event_queue: EventQueue, message: str
    ) -> None:
        context_id = context.context_id or context.task_id
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context_id,
                status=TaskStatus(
                    state=TaskState.failed,
                    timestamp=_utc_now(),
                    message=_text_message(message),
                ),
                final=True,
            )
        )

    async def _input_required(
        self, context: RequestContext, event_queue: EventQueue, message: str
    ) -> None:
        context_id = context.context_id or context.task_id
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context_id,
                status=TaskStatus(
                    state=TaskState.input_required,
                    timestamp=_utc_now(),
                    message=_text_message(message),
                ),
                final=False,
            )
        )
