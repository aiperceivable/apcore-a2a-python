"""Shared helpers for the cross-language conformance runners (Algorithm A01).

Fixtures live in the apcore-a2a spec repo at ``conformance/fixtures/*.json`` and
are shared verbatim with the TypeScript and Rust SDK runners. The spec repo is
resolved from ``APCORE_A2A_SPEC_REPO`` (set by CI to the checked-out spec repo),
defaulting to the sibling ``../apcore-a2a`` checkout for local runs. When the
fixtures are absent the runners ``pytest.skip`` so the SDK still tests stand-alone.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

_DEFAULT_SPEC_REPO = Path(__file__).resolve().parents[3] / "apcore-a2a"
SPEC_REPO_ROOT = Path(os.environ.get("APCORE_A2A_SPEC_REPO", str(_DEFAULT_SPEC_REPO)))
FIXTURES_DIR = SPEC_REPO_ROOT / "conformance" / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    """Load a fixture JSON file, skipping the test module if it is unavailable."""
    path = FIXTURES_DIR / name
    if not path.is_file():
        pytest.skip(f"conformance fixture not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def partial_match(expected: Any, actual: Any, path: str = "") -> str | None:
    """Deep partial match: every key/value in ``expected`` must appear in ``actual``.

    Extra keys in ``actual`` are allowed (objects) and lists must contain at least
    the expected positional items. Returns ``None`` on success or a human-readable
    path-qualified message describing the first mismatch.
    """
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return f"{path or '<root>'}: expected object, got {type(actual).__name__}"
        for key, value in expected.items():
            sub = f"{path}.{key}" if path else key
            if key not in actual:
                return f"{sub}: missing key (actual keys: {sorted(actual)})"
            err = partial_match(value, actual[key], sub)
            if err:
                return err
        return None
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return f"{path}: expected array, got {type(actual).__name__}"
        if len(actual) < len(expected):
            return f"{path}: expected >= {len(expected)} items, got {len(actual)}"
        for i, value in enumerate(expected):
            err = partial_match(value, actual[i], f"{path}[{i}]")
            if err:
                return err
        return None
    if expected != actual:
        return f"{path or '<root>'}: expected {expected!r}, got {actual!r}"
    return None
