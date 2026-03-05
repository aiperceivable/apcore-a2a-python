"""Explorer UI — implementation delegated to __init__.py (F-10)."""
from __future__ import annotations

# Re-export for backwards compatibility; implementation lives in __init__.py
from apcore_a2a.explorer import create_explorer_mount  # noqa: F401

__all__ = ["create_explorer_mount"]
