"""PartConverter: bidirectional converter between A2A Parts and apcore inputs/outputs."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from a2a.types import Artifact, Part
from google.protobuf import struct_pb2
from google.protobuf.json_format import MessageToDict, ParseDict

from apcore_a2a.adapters.schema import SchemaConverter


class PartConverter:
    """Converts a2a.types.Part objects to/from apcore module inputs/outputs."""

    def __init__(self, schema_converter: SchemaConverter | None = None) -> None:
        self._schema_converter = schema_converter or SchemaConverter()

    def parts_to_input(self, parts: list[Part], descriptor: Any) -> dict | str:
        """Convert a2a.types.Part list to apcore module input.

        Args:
            parts: List of a2a.types.Part protobuf messages.
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
        which = part.WhichOneof("content")

        if which == "text":
            input_schema = getattr(descriptor, "input_schema", None)
            root_type = self._schema_converter.detect_root_type(input_schema)
            if root_type == "object":
                try:
                    return json.loads(part.text)
                except json.JSONDecodeError as e:
                    raise ValueError(f"TextPart text is not valid JSON: {e}") from e
            return part.text

        if which == "data":
            return MessageToDict(part.data)

        if which in ("url", "raw"):
            raise ValueError("FilePart is not supported")

        raise ValueError("Empty or unknown part content")

    def output_to_parts(self, output: Any, task_id: str = "") -> Artifact:
        """Convert apcore module output to a2a.types.Artifact.

        Args:
            output: Module output value (str, dict, None, or other).
            task_id: Task ID used to build artifact_id.

        Returns:
            a2a.types.Artifact protobuf message.
        """
        artifact_id = f"art-{task_id or str(uuid4())}"

        if output is None:
            return Artifact(artifact_id=artifact_id)

        if isinstance(output, str):
            return Artifact(artifact_id=artifact_id, parts=[Part(text=output)])

        if isinstance(output, dict):
            return Artifact(artifact_id=artifact_id, parts=[Part(data=ParseDict(output, struct_pb2.Value()))])

        if isinstance(output, list):
            # Serialize lists as compact JSON (no spaces) to byte-match the
            # TypeScript (JSON.stringify) and Rust (serde_json) adapters; the
            # default json.dumps separators emit "[1, 2, 3]" which diverges.
            return Artifact(artifact_id=artifact_id, parts=[Part(text=json.dumps(output, separators=(",", ":")))])

        # Any other scalar type: emit a JSON literal to match TS/Rust
        # (e.g. bool -> "true"/"false", int/float -> their JSON form).
        # Fall back to str() only for non-JSON-serializable objects.
        try:
            text = json.dumps(output, separators=(",", ":"))
        except TypeError:
            text = str(output)
        return Artifact(artifact_id=artifact_id, parts=[Part(text=text)])
