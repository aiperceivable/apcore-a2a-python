"""SchemaConverter: apcore schemas → A2A DataPart / input schemas."""

from __future__ import annotations

import copy
from typing import Any

from apcore_toolkit import deep_resolve_refs


class SchemaConverter:
    """Converts apcore ModuleDescriptor schemas to A2A-compatible schemas.

    Key transformations:
    - Empty schemas → {"type": "object", "properties": {}}
    - Schemas with $defs and $ref → inline all refs, strip $defs
    - Ensures all schemas have "type": "object" at the root level
    - Returns deep copies (doesn't modify original schemas)
    """

    def convert_input_schema(self, descriptor: Any) -> dict[str, Any]:
        """Convert apcore ModuleDescriptor.input_schema for A2A input usage.

        Args:
            descriptor: ModuleDescriptor with input_schema attribute

        Returns:
            A2A-compatible schema dict with $refs inlined and $defs removed
        """
        schema = descriptor.input_schema
        return self._convert_schema(schema)

    def convert_output_schema(self, descriptor: Any) -> dict[str, Any]:
        """Convert apcore ModuleDescriptor.output_schema for A2A output usage.

        Args:
            descriptor: ModuleDescriptor with output_schema attribute

        Returns:
            A2A-compatible schema dict with $refs inlined and $defs removed
        """
        schema = descriptor.output_schema
        return self._convert_schema(schema)

    def detect_root_type(self, schema: dict[str, Any] | None) -> str:
        """Return 'string', 'object', or 'unknown'.

        Args:
            schema: JSON Schema dict or None

        Returns:
            Root type string
        """
        if not schema:
            return "unknown"
        root_type = schema.get("type")
        if root_type == "string":
            return "string"
        if root_type == "object" or "properties" in schema:
            return "object"
        return "unknown"

    def _convert_schema(self, schema: dict[str, Any] | None) -> dict[str, Any]:
        """Convert a schema, applying all transformations.

        Args:
            schema: JSON Schema dict to convert or None

        Returns:
            Converted schema with $refs inlined, $defs removed, and type ensured
        """
        # Make a deep copy to avoid modifying the original
        schema = copy.deepcopy(schema)

        # Handle empty/None schema
        if not schema:
            return {"type": "object", "properties": {}}

        # Inline $refs if present. Delegate JSON $ref resolution to the shared
        # apcore-toolkit resolver (RFC 6901 pointer walk, handles $defs /
        # definitions / components, nested allOf/anyOf/oneOf/items, and is
        # depth-capped against circular refs) — same helper used by apcore-mcp
        # and apcore-cli. The schema itself is the resolution document because
        # Pydantic emits self-contained "#/$defs/..." pointers.
        if "$defs" in schema:
            schema = deep_resolve_refs(schema, schema)
            # Remove $defs from the final schema
            schema.pop("$defs", None)

        # Ensure schema has type: object
        schema = self._ensure_object_type(schema)

        return schema

    def _ensure_object_type(self, schema: dict[str, Any]) -> dict[str, Any]:
        """Ensure schema has type: object with properties.

        Args:
            schema: Schema dict that may be missing "type"

        Returns:
            Schema with "type": "object" guaranteed at root level
        """
        # If schema doesn't have a type, add type: object
        if "type" not in schema:
            schema["type"] = "object"

        # If schema has properties but no type, ensure it's an object
        if "properties" in schema and schema.get("type") != "object":
            schema["type"] = "object"

        return schema
