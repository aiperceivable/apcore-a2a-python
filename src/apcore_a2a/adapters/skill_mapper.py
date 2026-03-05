"""SkillMapper: ModuleDescriptor → a2a.types.AgentSkill."""

from __future__ import annotations

from typing import Any

from a2a.types import AgentSkill


class SkillMapper:
    """Converts apcore ModuleDescriptor to a2a.types.AgentSkill."""

    def to_skill(self, descriptor: Any) -> AgentSkill | None:
        """Convert a ModuleDescriptor to an a2a.types.AgentSkill.

        Args:
            descriptor: ModuleDescriptor with module_id, description, etc.

        Returns:
            AgentSkill Pydantic model, or None if descriptor has no description.
        """
        description = getattr(descriptor, "description", None)
        if not description:
            return None

        return AgentSkill(
            id=descriptor.module_id,
            name=self._humanize_module_id(descriptor.module_id),
            description=description,
            tags=list(getattr(descriptor, "tags", []) or []),
            input_modes=self._compute_input_modes(descriptor),
            output_modes=self._compute_output_modes(descriptor),
            examples=self._build_examples(descriptor),
        )

    def _humanize_module_id(self, module_id: str) -> str:
        """Convert module_id to a human-readable name.

        Examples:
            "image.resize" → "Image Resize"
            "text_process.clean_up" → "Text Process Clean Up"
            "ping" → "Ping"
        """
        return module_id.replace(".", " ").replace("_", " ").title()

    def _compute_input_modes(self, descriptor: Any) -> list[str]:
        """Compute A2A input_modes from the descriptor's input_schema."""
        schema = getattr(descriptor, "input_schema", None)
        if not schema:
            return ["text/plain"]

        root_type = schema.get("type")
        if root_type == "string":
            return ["application/json", "text/plain"]

        return ["application/json"]

    def _compute_output_modes(self, descriptor: Any) -> list[str]:
        """Compute A2A output_modes from the descriptor's output_schema."""
        schema = getattr(descriptor, "output_schema", None)
        if not schema:
            return ["text/plain"]
        return ["application/json"]

    def _build_examples(self, descriptor: Any) -> list[str]:
        """Build up to 10 A2A example strings from the descriptor's examples list."""
        examples = getattr(descriptor, "examples", None) or []
        result = []
        for ex in examples[:10]:
            title = getattr(ex, "title", None)
            if title:
                result.append(str(title))
        return result

    def _build_extensions(self, annotations: Any) -> dict | None:
        """Build apcore skill extensions dict from module annotations.

        Returns a dict with apcore annotation flags, or None if annotations is None.

        Structure:
            {"apcore": {"annotations": {"readonly": bool, "destructive": bool,
                        "idempotent": bool, "requires_approval": bool, "open_world": bool}}}
        """
        if annotations is None:
            return None
        return {
            "apcore": {
                "annotations": {
                    "readonly": bool(getattr(annotations, "readonly", False)),
                    "destructive": bool(getattr(annotations, "destructive", False)),
                    "idempotent": bool(getattr(annotations, "idempotent", False)),
                    "requires_approval": bool(getattr(annotations, "requires_approval", False)),
                    "open_world": bool(getattr(annotations, "open_world", True)),
                }
            }
        }
