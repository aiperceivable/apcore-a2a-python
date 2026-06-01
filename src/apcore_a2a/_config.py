"""Config namespace registration and resolution for apcore-a2a (apcore 0.22)."""

from __future__ import annotations

import logging
import os
from typing import Any

from apcore.config import Config

logger = logging.getLogger(__name__)

A2A_NAMESPACE = "apcore-a2a"
A2A_ENV_PREFIX = "APCORE_A2A"

A2A_DEFAULTS: dict[str, Any] = {
    "execution_timeout": 300,
    "cors_origins": [],
    "explorer": False,
    "metrics": False,
    "push_notifications": False,
}


def register_a2a_namespace() -> None:
    """Register the 'apcore-a2a' config namespace. Safe to call multiple times."""
    try:
        Config.register_namespace(
            A2A_NAMESPACE,
            env_prefix=A2A_ENV_PREFIX,
            defaults=A2A_DEFAULTS,
        )
    except Exception:
        logger.debug("A2A config namespace already registered")


def get_a2a_setting(key: str, fallback: Any = None) -> Any:
    """Resolve an ``apcore-a2a`` namespace setting through apcore's Config.

    Delegates to :meth:`apcore.config.Config.load` so that values from an
    apcore config file and ``APCORE_A2A_*`` environment overrides are applied
    by apcore itself (namespace mode), exactly like other apcore bindings
    (e.g. apcore-mcp). Falls back to the registered namespace default when the
    key is unset.
    """
    register_a2a_namespace()
    value = Config.load(validate=False).get(f"{A2A_NAMESPACE}.{key}")
    return fallback if value is None else value


def resolve_execution_timeout(explicit: int | None) -> int:
    """Resolve the task execution timeout (seconds).

    Precedence: explicit argument > apcore Config (``apcore-a2a.execution_timeout``,
    incl. ``APCORE_A2A_EXECUTION_TIMEOUT`` env override in namespace mode) >
    bare ``APCORE_A2A_EXECUTION_TIMEOUT`` env var (honored even without a config
    file) > the registered namespace default.
    """
    if explicit is not None:
        return int(explicit)
    value = get_a2a_setting("execution_timeout")
    if value is None:
        env_val = os.environ.get(f"{A2A_ENV_PREFIX}_EXECUTION_TIMEOUT")
        value = env_val if env_val is not None else A2A_DEFAULTS["execution_timeout"]
    return int(value)
