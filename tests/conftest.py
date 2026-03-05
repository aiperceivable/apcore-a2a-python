"""Shared test fixtures and lightweight apcore stubs for unit testing.

All stubs are pure Python dataclasses — no apcore dependency needed for unit tests.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# apcore stub types (mirrors apcore-mcp-python/tests/conftest.py pattern)
# ---------------------------------------------------------------------------


@dataclass
class ModuleAnnotations:
    readonly: bool = False
    destructive: bool = False
    idempotent: bool = False
    requires_approval: bool = False
    open_world: bool = True
    streaming: bool = False


@dataclass
class ModuleExample:
    title: str = ""
    inputs: dict[str, Any] = field(default_factory=dict)
    output: Any = None
    description: str = ""


@dataclass
class ModuleDescriptor:
    module_id: str = "test.module"
    description: str = "Test module"
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    name: str | None = None
    documentation: str | None = None
    version: str | None = None
    tags: list[str] = field(default_factory=list)
    annotations: ModuleAnnotations | None = field(default_factory=ModuleAnnotations)
    examples: list[ModuleExample] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Standard descriptor fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def simple_descriptor() -> ModuleDescriptor:
    """image.resize — flat input/output schema."""
    return ModuleDescriptor(
        module_id="image.resize",
        description="Resize an image to the specified dimensions",
        tags=["image", "transform"],
        input_schema={
            "type": "object",
            "properties": {
                "width": {"type": "integer", "description": "Target width in pixels"},
                "height": {"type": "integer", "description": "Target height in pixels"},
            },
            "required": ["width", "height"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "width": {"type": "integer"},
                "height": {"type": "integer"},
                "url": {"type": "string"},
            },
        },
        annotations=ModuleAnnotations(readonly=True, idempotent=True),
        examples=[
            ModuleExample(
                title="Resize to 800x600",
                inputs={"width": 800, "height": 600},
                output={"width": 800, "height": 600, "url": "https://example.com/img.png"},
            )
        ],
    )


@pytest.fixture
def empty_schema_descriptor() -> ModuleDescriptor:
    """system.ping — no input/output schema."""
    return ModuleDescriptor(
        module_id="system.ping",
        description="Ping the system to check health",
        tags=["system"],
        input_schema=None,
        output_schema=None,
        annotations=ModuleAnnotations(readonly=True),
    )


@pytest.fixture
def nested_schema_descriptor() -> ModuleDescriptor:
    """workflow.execute — schema with $defs/$ref."""
    return ModuleDescriptor(
        module_id="workflow.execute",
        description="Execute a workflow",
        input_schema={
            "type": "object",
            "$defs": {
                "Step": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "action": {"type": "string"},
                    },
                    "required": ["name", "action"],
                }
            },
            "properties": {
                "steps": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/Step"},
                }
            },
        },
        output_schema={"type": "object", "properties": {"result": {"type": "string"}}},
    )


@pytest.fixture
def destructive_descriptor() -> ModuleDescriptor:
    """file.delete — destructive + requires approval."""
    return ModuleDescriptor(
        module_id="file.delete",
        description="Delete a file permanently",
        tags=["file", "dangerous"],
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string", "description": "File path to delete"}},
            "required": ["path"],
        },
        annotations=ModuleAnnotations(destructive=True, requires_approval=True),
    )


@pytest.fixture
def no_annotations_descriptor() -> ModuleDescriptor:
    """text.echo — None annotations."""
    return ModuleDescriptor(
        module_id="text.echo",
        description="Echo text back",
        input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"text": {"type": "string"}}},
        annotations=None,
    )


@pytest.fixture
def streaming_descriptor() -> ModuleDescriptor:
    """data.stream — supports streaming."""
    return ModuleDescriptor(
        module_id="data.stream",
        description="Stream data chunks",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"chunk": {"type": "string"}}},
        annotations=ModuleAnnotations(streaming=True, readonly=True),
    )


# ---------------------------------------------------------------------------
# Registry / Executor stubs
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_registry(simple_descriptor, empty_schema_descriptor, destructive_descriptor):
    """Mock apcore Registry with three modules."""
    registry = MagicMock()
    registry.list.return_value = ["image.resize", "system.ping", "file.delete"]
    registry.get_definition.side_effect = {
        "image.resize": simple_descriptor,
        "system.ping": empty_schema_descriptor,
        "file.delete": destructive_descriptor,
    }.get
    return registry


@pytest.fixture
def mock_executor():
    """Mock apcore Executor."""
    executor = MagicMock()
    executor.call_async = AsyncMock(return_value={"result": "ok"})
    executor.registry = MagicMock()
    executor.registry.list.return_value = ["image.resize"]
    return executor


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def make_jsonrpc_request(method: str, params: dict, req_id: str = "test-1") -> dict:
    """Build a JSON-RPC 2.0 request dict."""
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": method,
        "params": params,
    }


def make_message_send_params(
    text: str = "hello",
    skill_id: str = "image.resize",
    context_id: str | None = None,
) -> dict:
    """Build message/send params."""
    params: dict = {
        "message": {
            "role": "user",
            "parts": [{"kind": "text", "text": text}],
        },
        "metadata": {"skillId": skill_id},
    }
    if context_id:
        params["contextId"] = context_id
    return params
