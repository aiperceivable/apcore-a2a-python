"""Config namespace registration for apcore-a2a (apcore 0.15.1, §9.13)."""

from __future__ import annotations

import logging

from apcore.config import Config

logger = logging.getLogger(__name__)

A2A_NAMESPACE = "apcore-a2a"
A2A_ENV_PREFIX = "APCORE_A2A"

A2A_DEFAULTS: dict[str, object] = {
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
