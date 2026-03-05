"""Public API: serve() and async_serve() implementations."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from starlette.applications import Starlette

from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore

from apcore_a2a.server.factory import A2AServerFactory

# CFG1: allow execution_timeout to be configured via environment variable
_DEFAULT_EXECUTION_TIMEOUT = int(os.environ.get("A2A_EXECUTION_TIMEOUT", "300"))

logger = logging.getLogger(__name__)

# Required methods for protocol validation
_AUTH_REQUIRED = ("authenticate", "security_schemes")
# a2a-sdk TaskStore interface: save, get, delete (no list method)
_TASK_STORE_REQUIRED = ("save", "get", "delete")


def _resolve_registry_and_executor(
    registry_or_executor: Any,
) -> tuple[Any, Any]:
    """Duck-type resolve a registry and executor from the given object.

    Accepted inputs:
    - An apcore Registry (has ``list`` and ``get_definition`` methods).
    - An apcore Executor (has ``call_async`` method; registry obtained from
      ``obj.registry``).

    Returns:
        (registry, executor) tuple.  When only a Registry is supplied the
        executor is the registry itself (the factory only calls ``call_async``
        on the executor, so it must be present on the registry OR the registry
        is used as a fallback duck-type executor stub).

    Raises:
        TypeError: if the object matches neither shape.
    """
    has_list = hasattr(registry_or_executor, "list")
    has_get_def = hasattr(registry_or_executor, "get_definition")
    has_call_async = hasattr(registry_or_executor, "call_async")

    # Check executor first — it's more specific (call_async is distinctive).
    # A real Executor will have call_async; a real Registry typically will not.
    # This ordering prevents a MagicMock executor (which has all attrs) from
    # being mis-classified as a Registry.
    if has_call_async:
        # It looks like an Executor
        executor = registry_or_executor
        registry = getattr(executor, "registry", None)
        if registry is None:
            raise TypeError(
                "Expected apcore Registry or Executor: executor has no .registry attribute"
            )
        return registry, executor

    if has_list and has_get_def:
        # It looks like a Registry (and does not have call_async)
        registry = registry_or_executor
        # Use a dedicated .executor if available, otherwise use registry itself
        # as the executor duck-type (the factory only needs call_async on it).
        executor = getattr(registry_or_executor, "executor", registry_or_executor)
        return registry, executor

    raise TypeError("Expected apcore Registry or Executor")


async def async_serve(
    registry_or_executor: Any,
    *,
    name: str | None = None,
    description: str | None = None,
    version: str | None = None,
    url: str = "http://localhost:8000",
    auth: Any | None = None,
    task_store: Any | None = None,
    cors_origins: list[str] | None = None,
    push_notifications: bool = False,
    explorer: bool = False,
    explorer_prefix: str = "/explorer",
    cancel_on_disconnect: bool = True,
    execution_timeout: int = _DEFAULT_EXECUTION_TIMEOUT,
    metrics: bool = False,
) -> Starlette:
    """Build and return a Starlette ASGI app for an A2A agent.

    Args:
        registry_or_executor: An apcore Registry or Executor instance.
        name: Agent name; falls back to registry config then "apcore-agent".
        description: Agent description; falls back to registry config then
            auto-generated from module count.
        version: Agent version; falls back to registry config then "0.0.0".
        url: Public URL of the agent (default "http://localhost:8000").
        auth: Optional Authenticator implementing authenticate() and
            security_schemes().
        task_store: Optional TaskStore; defaults to InMemoryTaskStore().
        cors_origins: Optional list of allowed CORS origins.
        push_notifications: Enable push notification capability.
        explorer: Enable the A2A explorer UI.
        explorer_prefix: URL prefix for the explorer (default "/explorer").
        cancel_on_disconnect: Deprecated. Has no effect; DefaultRequestHandler
            does not support disabling cancel-on-disconnect.
        execution_timeout: Task execution timeout in seconds. Can also be set
            via the A2A_EXECUTION_TIMEOUT environment variable.

    Returns:
        A configured Starlette ASGI application.

    Raises:
        TypeError: If registry_or_executor is not a Registry or Executor,
            if auth is missing required protocol methods, or if task_store is
            missing required protocol methods.
        ValueError: If the registry contains zero modules.
    """
    # Step 1: Resolve registry and executor
    registry, executor = _resolve_registry_and_executor(registry_or_executor)

    # Step 2: Validate registry has at least one module
    modules = registry.list()
    if len(modules) == 0:
        raise ValueError(
            "Registry contains zero modules; at least one module is required to serve an A2A agent"
        )

    # Step 3: Resolve metadata with fallbacks
    project_config: dict[str, Any] = (
        getattr(registry, "config", {}) or {}
    ).get("project", {}) or {}

    resolved_name = name or project_config.get("name") or "apcore-agent"
    resolved_version = version or project_config.get("version") or "0.0.0"
    resolved_description = (
        description
        or project_config.get("description")
        or f"apcore agent with {len(modules)} skills"
    )

    # Step 4: Default task_store to InMemoryTaskStore if not provided
    if task_store is None:
        task_store = InMemoryTaskStore()

    # Step 5: Protocol validation
    if auth is not None:
        missing_auth = [m for m in _AUTH_REQUIRED if not hasattr(auth, m)]
        if missing_auth:
            raise TypeError(
                f"auth missing required methods: {missing_auth}"
            )

    missing_store = [m for m in _TASK_STORE_REQUIRED if not hasattr(task_store, m)]
    if missing_store:
        raise TypeError(
            f"task_store missing required methods: {missing_store}"
        )

    # Step 6: Build the ASGI app via A2AServerFactory
    factory = A2AServerFactory()
    app, _agent_card = factory.create(
        registry,
        executor,
        name=resolved_name,
        description=resolved_description,
        version=resolved_version,
        url=url,
        task_store=task_store,
        auth=auth,
        push_notifications=push_notifications,
        cancel_on_disconnect=cancel_on_disconnect,
        execution_timeout=execution_timeout,
        cors_origins=cors_origins,
        explorer=explorer,
        explorer_prefix=explorer_prefix,
        metrics=metrics,
    )

    # Step 7: Return the Starlette app
    return app


def serve(
    registry_or_executor: Any,
    *,
    host: str = "0.0.0.0",
    port: int = 8000,
    name: str | None = None,
    description: str | None = None,
    version: str | None = None,
    url: str | None = None,
    auth: Any | None = None,
    task_store: Any | None = None,
    cors_origins: list[str] | None = None,
    push_notifications: bool = False,
    explorer: bool = False,
    explorer_prefix: str = "/explorer",
    cancel_on_disconnect: bool = True,
    shutdown_timeout: int = 30,
    execution_timeout: int = _DEFAULT_EXECUTION_TIMEOUT,
    log_level: str | None = None,
    metrics: bool = False,
) -> None:
    """Launch an A2A agent server (blocking).

    Builds the ASGI app via async_serve() and serves it with uvicorn.

    Args:
        registry_or_executor: An apcore Registry or Executor instance.
        host: Bind host (default "0.0.0.0").
        port: Bind port (default 8000).
        name: Agent name.
        description: Agent description.
        version: Agent version.
        url: Public URL; defaults to f"http://{host}:{port}".
        auth: Optional Authenticator.
        task_store: Optional TaskStore; defaults to InMemoryTaskStore().
        cors_origins: Allowed CORS origins.
        push_notifications: Enable push notifications.
        explorer: Enable explorer UI.
        explorer_prefix: URL prefix for explorer.
        cancel_on_disconnect: Deprecated. Has no effect.
        shutdown_timeout: Graceful shutdown timeout in seconds.
        execution_timeout: Task execution timeout in seconds. Can also be set
            via the A2A_EXECUTION_TIMEOUT environment variable.
        log_level: Optional log level string (e.g. "info", "debug").

    Raises:
        TypeError: Protocol violations in auth or task_store.
        ValueError: Zero modules in registry.
    """
    # Step 1: Configure logging
    if log_level is not None:
        logging.basicConfig(level=getattr(logging, log_level.upper(), logging.INFO))

    # Step 2: Resolve url default
    resolved_url = url or f"http://{host}:{port}"

    # Step 3: Run async_serve + uvicorn inside an event loop
    async def _main() -> None:
        import uvicorn

        app = await async_serve(
            registry_or_executor,
            name=name,
            description=description,
            version=version,
            url=resolved_url,
            auth=auth,
            task_store=task_store,
            cors_origins=cors_origins,
            push_notifications=push_notifications,
            explorer=explorer,
            explorer_prefix=explorer_prefix,
            cancel_on_disconnect=cancel_on_disconnect,
            execution_timeout=execution_timeout,
            metrics=metrics,
        )
        config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level=log_level or "info",
        )
        server = uvicorn.Server(config)
        await server.serve()

    asyncio.run(_main())
