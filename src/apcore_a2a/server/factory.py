"""A2AServerFactory: wires all components into a Starlette ASGI app via a2a-sdk."""

from __future__ import annotations

import contextlib
import logging
import time
import warnings
from dataclasses import dataclass
from typing import Any

from a2a.server.context import ServerCallContext
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes, create_rest_routes
from a2a.server.tasks.inmemory_push_notification_config_store import (
    InMemoryPushNotificationConfigStore,
)
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore as A2ATaskStore
from a2a.types import AgentCapabilities, AgentCard
from apcore.error_formatter import ErrorFormatterRegistry
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from apcore_a2a._config import register_a2a_namespace
from apcore_a2a.adapters.agent_card import AgentCardBuilder
from apcore_a2a.adapters.errors import ErrorMapper
from apcore_a2a.adapters.parts import PartConverter
from apcore_a2a.adapters.schema import SchemaConverter
from apcore_a2a.adapters.skill_mapper import SkillMapper
from apcore_a2a.server.executor import ApCoreAgentExecutor

logger = logging.getLogger(__name__)


@dataclass
class _MetricsState:
    """Simple in-process metrics counters."""

    active_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    canceled_tasks: int = 0
    input_required_tasks: int = 0
    total_requests: int = 0

    def __post_init__(self) -> None:
        # D1: use __post_init__ so _start_time is not exposed as a dataclass field
        self._start_time: float = time.monotonic()

    def uptime_seconds(self) -> float:
        return time.monotonic() - self._start_time

    def on_state_transition(self, old_state: str, new_state: str) -> None:
        """Update counters on task state change."""
        _active = {"submitted", "working", "input-required", "input_required"}
        _was_active = old_state in _active
        _now_active = new_state in _active

        if not _was_active and _now_active:
            self.active_tasks += 1
        elif _was_active and not _now_active:
            self.active_tasks = max(0, self.active_tasks - 1)

        if new_state == "completed":
            self.completed_tasks += 1
        elif new_state == "failed":
            self.failed_tasks += 1
        elif new_state == "canceled":
            self.canceled_tasks += 1
        elif new_state in ("input_required", "input-required"):
            self.input_required_tasks += 1


def _build_health_handler(task_store: Any, registry: Any, metrics: _MetricsState, version: str) -> Any:
    """Return a Starlette endpoint that serves /health."""

    async def handle_health(request: Request) -> JSONResponse:
        module_count = 0
        if registry is not None:
            with contextlib.suppress(Exception):
                module_count = len(registry.list())

        # Probe the store — a2a-sdk 1.0 requires a ServerCallContext argument
        ctx = ServerCallContext()
        try:
            await task_store.get("__health_probe__", ctx)
        except Exception as e:
            return JSONResponse(
                {
                    "status": "unhealthy",
                    "reason": f"Task store unavailable: {e}",
                    "uptime_seconds": metrics.uptime_seconds(),
                    "module_count": module_count,
                    "version": version,
                },
                status_code=503,
            )

        return JSONResponse(
            {
                "status": "healthy",
                "uptime_seconds": metrics.uptime_seconds(),
                "module_count": module_count,
                "version": version,
            }
        )

    return handle_health


def _build_metrics_handler(metrics: _MetricsState) -> Any:
    """Return a Starlette endpoint that serves /metrics."""

    async def handle_metrics(request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "active_tasks": metrics.active_tasks,
                "completed_tasks": metrics.completed_tasks,
                "failed_tasks": metrics.failed_tasks,
                "canceled_tasks": metrics.canceled_tasks,
                "input_required_tasks": metrics.input_required_tasks,
                "total_requests": metrics.total_requests,
                "uptime_seconds": metrics.uptime_seconds(),
            }
        )

    return handle_metrics


class _RequestCountMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that increments metrics.total_requests on each POST."""

    def __init__(self, app: Any, metrics: _MetricsState, **kwargs: Any) -> None:
        super().__init__(app, **kwargs)
        self._metrics = metrics

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        if request.method == "POST":
            self._metrics.total_requests += 1
        return await call_next(request)


class A2AServerFactory:
    def __init__(self) -> None:
        self._skill_mapper = SkillMapper()
        self._schema_converter = SchemaConverter()
        self._agent_card_builder = AgentCardBuilder(self._skill_mapper)
        self._error_mapper = ErrorMapper()
        self._part_converter = PartConverter(self._schema_converter)

        # apcore 0.22.0: register config namespace and error formatter
        register_a2a_namespace()
        try:
            ErrorFormatterRegistry.register("a2a", self._error_mapper)
        except Exception:
            # Already registered (e.g. multiple factory instances in tests)
            logger.debug("Error formatter 'a2a' already registered")

    def create(
        self,
        registry: Any,
        executor: Any,
        *,
        name: str,
        description: str,
        version: str,
        url: str,
        task_store: Any | None = None,
        auth: Any | None = None,
        push_notifications: bool = False,
        cancel_on_disconnect: bool = True,
        execution_timeout: int = 300,
        cors_origins: list[str] | None = None,
        explorer: bool = False,
        explorer_prefix: str = "/explorer",
        metrics: bool = False,
        sys_modules: bool = False,
    ) -> tuple[Starlette, AgentCard]:
        """Build ASGI app and AgentCard. Returns (app, agent_card)."""
        # C3: cancel_on_disconnect is not used by DefaultRequestHandler; warn when False
        if not cancel_on_disconnect:
            warnings.warn(
                "cancel_on_disconnect=False has no effect; DefaultRequestHandler does not "
                "support disabling cancel-on-disconnect. This parameter will be removed in "
                "a future version.",
                DeprecationWarning,
                stacklevel=2,
            )

        # Store params for register_module()
        self._name = name
        self._description = description
        self._version = version
        self._url = url
        self._registry = registry

        # Build security schemes — RAISES on failure (no silent except)
        security_schemes = None
        if auth is not None:
            security_schemes = auth.security_schemes()
        self._security_schemes = security_schemes

        # Build capabilities (a2a-sdk 1.0: no state_transition_history field)
        capabilities = AgentCapabilities(
            streaming=True,
            push_notifications=push_notifications,
            extended_agent_card=(auth is not None),
        )
        self._capabilities = capabilities

        # P1-B: register sys.* modules BEFORE building the AgentCard so they appear in skills.
        # Requires sys_modules=True and an executor that accepts .use() middleware.
        if sys_modules and hasattr(executor, "use"):
            try:
                from apcore import register_sys_modules
                from apcore.config import Config

                # Build a Config instance with sys_modules enabled.
                # Merge registry's own config (if any) so module-level settings are preserved.
                registry_cfg: dict[str, Any] = getattr(registry, "config", {}) or {}
                sys_data: dict[str, Any] = {
                    **registry_cfg,
                    "apcore": {
                        **registry_cfg.get("apcore", {}),
                        "sys_modules": {
                            **registry_cfg.get("apcore", {}).get("sys_modules", {}),
                            "enabled": True,
                        },
                    },
                }
                register_sys_modules(registry, executor, Config(data=sys_data))
                logger.info("Registered apcore system modules (sys.*)")
            except Exception:
                logger.warning("register_sys_modules failed — continuing without sys modules", exc_info=True)

        # Build AgentCard AFTER sys_modules so sys.* skills are included when enabled.
        agent_card = self._agent_card_builder.build(
            registry,
            name=name,
            description=description,
            version=version,
            url=url,
            capabilities=capabilities,
            security_schemes=security_schemes,
        )

        # C1: Build metrics state early so it can be wired into the executor
        metrics_state = _MetricsState()
        self._metrics_state = metrics_state

        # Build ApCoreAgentExecutor — C1: wire state-transition callback when metrics enabled
        on_state_change_cb = metrics_state.on_state_transition if metrics else None
        apcore_executor = ApCoreAgentExecutor(
            executor,
            self._part_converter,
            self._error_mapper,
            registry,
            execution_timeout,
            on_state_change=on_state_change_cb,
        )

        # P1-A: wire apcore observability middleware into the executor.
        # ObsLoggingMiddleware: structured per-call logging (always, low overhead).
        # ErrorHistoryMiddleware: tracks error patterns per module (only when metrics=True,
        # since register_sys_modules may already add it when sys_modules=True).
        if hasattr(executor, "use"):
            try:
                from apcore import ObsLoggingMiddleware

                executor.use(ObsLoggingMiddleware())
                if metrics and not sys_modules:
                    from apcore import ErrorHistoryMiddleware

                    executor.use(ErrorHistoryMiddleware())
            except Exception:
                logger.debug("Could not add observability middleware", exc_info=True)

        # Build task store
        sdk_task_store = task_store if task_store is not None else A2ATaskStore()
        self._task_store = sdk_task_store

        # Build push config store
        push_config_store = InMemoryPushNotificationConfigStore() if push_notifications else None

        # Build extended card
        extended_card = None
        if auth is not None:
            extended_card = self._agent_card_builder.build_extended(base_card=agent_card)

        # Build DefaultRequestHandler (a2a-sdk 1.0: agent_card is required 3rd arg)
        handler = DefaultRequestHandler(
            agent_executor=apcore_executor,
            task_store=sdk_task_store,
            agent_card=agent_card,
            push_config_store=push_config_store,
            extended_agent_card=extended_card,
        )

        # Build custom routes (health, optional metrics, optional explorer)
        custom_routes: list[Any] = []
        health_handler = _build_health_handler(sdk_task_store, registry, metrics_state, version)
        custom_routes.append(Route("/health", endpoint=health_handler, methods=["GET"]))

        if metrics:
            metrics_handler = _build_metrics_handler(metrics_state)
            custom_routes.append(Route("/metrics", endpoint=metrics_handler, methods=["GET"]))

        if explorer:
            try:
                from apcore_a2a.explorer import create_explorer_mount  # type: ignore[import]

                # D3: pass handler so explorer has access to the request handler
                explorer_mount = create_explorer_mount(
                    agent_card,
                    handler,
                    explorer_prefix=explorer_prefix,
                    registry=registry,
                )
                custom_routes.append(explorer_mount)
            except Exception:
                logger.warning("Explorer not available", exc_info=True)

        # Build middleware — RAISES on failure (no silent except)
        middleware: list[Middleware] = []

        # C2: add request counter as a proper Starlette middleware (not raw ASGI wrapping)
        # Insert first so it is the outermost layer and counts all POST requests
        if metrics:
            middleware.append(Middleware(_RequestCountMiddleware, metrics=metrics_state))

        if auth is not None:
            from apcore_a2a.auth.middleware import AuthMiddleware

            exempt_paths = {
                "/.well-known/agent.json",
                "/.well-known/agent-card.json",
                "/health",
                "/metrics",
            }
            exempt_prefixes: set[str] = set()
            if explorer:
                exempt_prefixes.add(explorer_prefix)
            middleware.append(
                Middleware(
                    AuthMiddleware,
                    authenticator=auth,
                    exempt_paths=exempt_paths,
                    exempt_prefixes=exempt_prefixes,
                )
            )
        if cors_origins:
            middleware.append(
                Middleware(
                    CORSMiddleware,
                    allow_origins=cors_origins,
                    allow_methods=["GET", "POST"],
                    allow_headers=["*"],
                )
            )

        # Build Starlette app from routes directly (a2a-sdk 1.0 route functions)
        # Serve agent card at both A2A 1.0 path and legacy 0.3.x path for backward compat
        agent_card_routes = create_agent_card_routes(agent_card=agent_card)
        agent_card_routes_legacy = create_agent_card_routes(agent_card=agent_card, card_url="/.well-known/agent.json")
        rest_routes = create_rest_routes(request_handler=handler)
        # enable_v0_3_compat: support legacy 0.3.x method names (message/send, tasks/get, etc.)
        jsonrpc_routes = create_jsonrpc_routes(request_handler=handler, rpc_url="/", enable_v0_3_compat=True)

        # custom_routes first: REST routes include Mount /{tenant} which catches all paths
        # including /explorer, /health etc. if placed before them.
        all_routes = custom_routes + agent_card_routes + agent_card_routes_legacy + list(rest_routes) + jsonrpc_routes

        app = Starlette(routes=all_routes, middleware=middleware)

        return app, agent_card

    def register_module(self, module_id: str, descriptor: Any) -> None:
        """Runtime dynamic registration."""
        registry = getattr(self, "_registry", None)
        if registry is not None:
            registry.register(module_id, descriptor)
        # Invalidate card cache so card_modifier picks up new skills
        self._agent_card_builder.invalidate_cache()
        logger.info("Dynamically registered module: %s", module_id)
