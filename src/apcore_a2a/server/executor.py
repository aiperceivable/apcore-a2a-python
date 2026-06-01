"""ApCoreAgentExecutor: bridges apcore execution to the a2a-sdk AgentExecutor ABC."""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events.event_queue_v2 import EventQueue
from a2a.types import (
    Artifact,
    Message,
    Part,
    Role,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from google.protobuf.timestamp_pb2 import Timestamp

# Imported at module level — no circular dependency (middleware.py does not import executor.py)
from apcore_a2a.auth.middleware import auth_identity_var

logger = logging.getLogger(__name__)


def _make_timestamp() -> Timestamp:
    ts = Timestamp()
    ts.FromDatetime(datetime.now(tz=UTC))
    return ts


def _make_status(state: int, message: Message | None = None) -> TaskStatus:
    status = TaskStatus(state=state)
    status.timestamp.CopyFrom(_make_timestamp())
    if message is not None:
        status.message.CopyFrom(message)
    return status


def _text_message(text: str) -> Message:
    return Message(
        role=Role.ROLE_AGENT,
        parts=[Part(text=text)],
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
        # P0-B: per-task CancelToken map
        self._cancel_tokens: dict[str, Any] = {}

    def _notify(self, old_state: str, new_state: str) -> None:
        if self._on_state_change is not None:
            try:
                self._on_state_change(old_state, new_state)
            except Exception:
                logger.debug("on_state_change callback raised", exc_info=True)

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        # a2a-sdk 1.0: Establish the Task in the store before any TaskStatusUpdateEvent
        context_id = context.context_id or context.task_id
        initial_task = Task(
            id=context.task_id,
            context_id=context_id,
            status=_make_status(TaskState.TASK_STATE_SUBMITTED),
        )
        await event_queue.enqueue_event(initial_task)

        # 1. Get skill_id from message metadata
        # metadata is a protobuf Struct; convert to dict for .get() access
        raw_metadata = context.message.metadata if context.message else None
        metadata: dict = dict(raw_metadata) if raw_metadata else {}
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
        parts = list(context.message.parts) if context.message else []
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

        # 4. Build apcore Identity context with CancelToken (P0-B)
        identity = auth_identity_var.get()
        apcore_ctx = None
        token = None
        try:
            from apcore import CancelToken, Context  # type: ignore[import]

            token = CancelToken()
            if context.task_id:
                self._cancel_tokens[context.task_id] = token
            # Map the A2A execution_timeout onto apcore's first-class
            # global_deadline (0.22.0). apcore enforces it cooperatively at
            # pipeline Step 8 AND between streaming chunks (executor.stream),
            # which is the only timeout the streaming path would otherwise have.
            # Stored as a monotonic deadline, matching apcore BuiltinContextStep.
            global_deadline = time.monotonic() + self._execution_timeout
            apcore_ctx = Context.create(
                identity=identity,
                cancel_token=token,
                global_deadline=global_deadline,
            )
        except Exception:
            pass

        # 5. Execute — streaming if available, single otherwise (P0-A)
        self._notify("submitted", "working")
        try:
            stream_fn = getattr(self._executor, "stream", None)
            _can_stream = (
                apcore_ctx is not None
                and stream_fn is not None
                and callable(stream_fn)
                and (inspect.isasyncgenfunction(stream_fn) or inspect.iscoroutinefunction(stream_fn))
            )

            if _can_stream:
                await self._execute_streaming(context, event_queue, skill_id, inputs, apcore_ctx, context_id)
            else:
                output = await self._execute_single(skill_id, inputs, apcore_ctx)
                # Publish artifact + completed event
                artifact = self._part_converter.output_to_parts(output, context.task_id)
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
                        status=_make_status(TaskState.TASK_STATE_COMPLETED),
                    )
                )
                self._notify("working", "completed")
        except asyncio.CancelledError:
            raise  # let a2a-sdk handle asyncio cancellation
        except TimeoutError:
            self._notify("working", "failed")
            await self._fail(context, event_queue, "Execution timed out")
        except Exception as exc:
            code = getattr(exc, "code", None)
            if code == "MODULE_TIMEOUT":
                # apcore enforced global_deadline (streaming or cooperative step)
                self._notify("working", "failed")
                await self._fail(context, event_queue, "Execution timed out")
            elif code == "EXECUTION_CANCELLED":
                # P0-C: cooperative cancellation via CancelToken
                self._notify("working", "canceled")
                await self._emit_canceled(context, event_queue, "Execution cancelled")
            elif code == "APPROVAL_PENDING":
                self._notify("working", "input_required")
                await self._input_required(context, event_queue, str(exc))
            else:
                logger.exception("Execution failed for task %s skill %s", context.task_id, skill_id)
                self._notify("working", "failed")
                await self._fail(context, event_queue, "Internal server error")
        finally:
            self._cancel_tokens.pop(context.task_id, None)

    async def _execute_streaming(
        self,
        context: RequestContext,
        event_queue: EventQueue,
        skill_id: str,
        inputs: Any,
        apcore_ctx: Any,
        context_id: str,
    ) -> None:
        """Stream chunks from executor.stream(), emitting TaskArtifactUpdateEvents."""
        artifact_id = f"art-{context.task_id or str(uuid4())}"
        chunk_index = 0
        async for chunk in self._executor.stream(skill_id, inputs, apcore_ctx):
            parts = self._part_converter.output_to_parts(chunk, context.task_id).parts
            await event_queue.enqueue_event(
                TaskArtifactUpdateEvent(
                    task_id=context.task_id,
                    context_id=context_id,
                    artifact=Artifact(artifact_id=artifact_id, parts=parts),
                    append=(chunk_index > 0),
                    last_chunk=False,
                )
            )
            chunk_index += 1
        # Emit last_chunk=True to signal stream end
        await event_queue.enqueue_event(
            TaskArtifactUpdateEvent(
                task_id=context.task_id,
                context_id=context_id,
                artifact=Artifact(artifact_id=artifact_id),
                append=True,
                last_chunk=True,
            )
        )
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context_id,
                status=_make_status(TaskState.TASK_STATE_COMPLETED),
            )
        )
        self._notify("working", "completed")

    async def _execute_single(self, skill_id: str, inputs: Any, apcore_ctx: Any) -> Any:
        """Single call_async() execution with timeout."""
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
        return await asyncio.wait_for(coro, timeout=self._execution_timeout)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        # P0-B: Signal cooperative cancellation BEFORE emitting the canceled status
        token = self._cancel_tokens.pop(context.task_id, None)
        if token is not None:
            token.cancel()
        context_id = context.context_id or context.task_id
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context_id,
                status=_make_status(
                    TaskState.TASK_STATE_CANCELED,
                    _text_message("Canceled by client"),
                ),
            )
        )
        self._notify("working", "canceled")

    async def _emit_canceled(self, context: RequestContext, event_queue: EventQueue, message: str) -> None:
        """Emit CANCELED status (for cooperative cancellation via CancelToken)."""
        context_id = context.context_id or context.task_id
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context_id,
                status=_make_status(
                    TaskState.TASK_STATE_CANCELED,
                    _text_message(message),
                ),
            )
        )

    async def _fail(self, context: RequestContext, event_queue: EventQueue, message: str) -> None:
        context_id = context.context_id or context.task_id
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context_id,
                status=_make_status(
                    TaskState.TASK_STATE_FAILED,
                    _text_message(message),
                ),
            )
        )

    async def _input_required(self, context: RequestContext, event_queue: EventQueue, message: str) -> None:
        context_id = context.context_id or context.task_id
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context_id,
                status=_make_status(
                    TaskState.TASK_STATE_INPUT_REQUIRED,
                    _text_message(message),
                ),
            )
        )
