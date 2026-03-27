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

        # Resolve display overlay fields (§5.13)
        metadata = getattr(descriptor, "metadata", None) or {}
        display = metadata.get("display") or {}
        a2a_display = display.get("a2a") or {}

        skill_name: str = (
            a2a_display.get("alias") or display.get("alias") or self._humanize_module_id(descriptor.module_id)
        )
        skill_description: str = a2a_display.get("description") or display.get("description") or description

        # Append guidance if present
        guidance: str | None = a2a_display.get("guidance") or display.get("guidance")
        if guidance:
            skill_description = f"{skill_description}\n\nGuidance: {guidance}"

        resolved_tags: list[str] = list(display.get("tags") or []) or list(getattr(descriptor, "tags", []) or [])

        return AgentSkill(
            id=descriptor.module_id,
            name=skill_name,
            description=skill_description,
            tags=resolved_tags,
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
