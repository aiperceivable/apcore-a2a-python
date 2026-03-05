"""PartConverter: bidirectional converter between A2A Parts and apcore inputs/outputs."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from a2a.types import Artifact, DataPart, FilePart, Part, TextPart

from apcore_a2a.adapters.schema import SchemaConverter


class PartConverter:
    """Converts a2a.types.Part objects to/from apcore module inputs/outputs."""

    def __init__(self, schema_converter: SchemaConverter | None = None) -> None:
        self._schema_converter = schema_converter or SchemaConverter()

    def parts_to_input(self, parts: list[Part], descriptor: Any) -> dict | str:
        """Convert a2a.types.Part list to apcore module input.

        Args:
            parts: List of a2a.types.Part Pydantic models.
            descriptor: ModuleDescriptor (used for schema-aware conversion).

        Returns:
            String for text input or dict for data/JSON input.

        Raises:
            ValueError: If parts is empty or contains multiple parts.
        """
        if not parts:
            raise ValueError("Message must contain at least one Part")

        if len(parts) > 1:
            raise ValueError("Multiple parts are not supported; expected exactly one Part")

        part = parts[0]
        root = part.root

        if isinstance(root, TextPart):
            input_schema = getattr(descriptor, "input_schema", None)
            root_type = self._schema_converter.detect_root_type(input_schema)
            if root_type == "object":
                try:
                    return json.loads(root.text)
                except json.JSONDecodeError as e:
                    raise ValueError(f"TextPart text is not valid JSON: {e}") from e
            return root.text

        if isinstance(root, DataPart):
            return root.data

        if isinstance(root, FilePart):
            raise ValueError("FilePart is not supported")

        raise ValueError(f"Unsupported part type: {type(root)!r}")

    def output_to_parts(self, output: Any, task_id: str = "") -> Artifact:
        """Convert apcore module output to a2a.types.Artifact.

        Args:
            output: Module output value (str, dict, None, or other).
            task_id: Task ID used to build artifact_id.

        Returns:
            a2a.types.Artifact Pydantic model.
        """
        artifact_id = f"art-{task_id or str(uuid4())}"

        if output is None:
            return Artifact(artifact_id=artifact_id, parts=[])

        if isinstance(output, str):
            parts = [Part(root=TextPart(text=output))]
            return Artifact(artifact_id=artifact_id, parts=parts)

        if isinstance(output, dict):
            parts = [Part(root=DataPart(data=output))]
            return Artifact(artifact_id=artifact_id, parts=parts)

        if isinstance(output, list):
            # Serialize lists as JSON rather than Python repr
            parts = [Part(root=TextPart(text=json.dumps(output)))]
            return Artifact(artifact_id=artifact_id, parts=parts)

        # Any other type: convert to string
        parts = [Part(root=TextPart(text=str(output)))]
        return Artifact(artifact_id=artifact_id, parts=parts)
