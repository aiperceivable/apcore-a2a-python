"""SkillMapper: ModuleDescriptor → a2a.types.AgentSkill."""

from __future__ import annotations

from typing import Any

from a2a.types import AgentSkill

from apcore_a2a.adapters.schema import SchemaConverter

# The four behavioral annotations promoted onto the A2A wire, with the tag each
# becomes. Order is fixed so the card is byte-identical across the three
# bindings (srs FR-SKL-004 criterion 8).
_ANNOTATION_TAGS: tuple[tuple[str, str], ...] = (
    ("readonly", "apcore:readonly"),
    ("destructive", "apcore:destructive"),
    ("idempotent", "apcore:idempotent"),
    ("requires_approval", "apcore:requires-approval"),
)


def _append_annotation_tags(tags: list[str], descriptor: Any) -> None:
    """Append apcore's behavioral annotations to a skill's tags (srs FR-SKL-004).

    A2A 1.0 ``AgentSkill`` is ``{id, name, description, tags, examples,
    input_modes, output_modes, security_requirements}`` — there is no
    ``extensions`` and no ``metadata`` member, and here the type is generated
    from the A2A protobuf schema, so a vendor field cannot be added at all.
    ``tags`` is the only carrier that exists. The ``apcore:`` prefix keeps these
    out of the module's own flat tag namespace, where a user tag named
    ``destructive`` would otherwise be indistinguishable from the annotation.

    Without this the Agent Card carried enough for a caller to *construct* a call
    and not enough to judge whether making it is safe. It is also what makes
    retry semantics usable: ``retryable`` is a property of the error, but whether
    a retry is safe is a property of the operation, and a timeout is retryable
    for a read and dangerous for a non-idempotent mutation.

    Only ``True`` flags are emitted, matching how the apcore MCP binding maps the
    same annotations onto optional ``readOnlyHint`` / ``destructiveHint`` /
    ``idempotentHint``. Absence means "not asserted", never "asserted False".
    """
    annotations = getattr(descriptor, "annotations", None)
    if annotations is None:
        return
    for field, tag in _ANNOTATION_TAGS:
        value = annotations.get(field) if isinstance(annotations, dict) else getattr(annotations, field, None)
        if value and tag not in tags:
            tags.append(tag)


def requires_approval(descriptor: Any) -> bool:
    """Whether a module is gated behind human approval.

    Used by the Agent Card builder to withhold the skill from the public card
    (srs FR-AGC-003) and restore it on the extended one (srs FR-AGC-004).
    """
    annotations = getattr(descriptor, "annotations", None)
    if annotations is None:
        return False
    value = (
        annotations.get("requires_approval")
        if isinstance(annotations, dict)
        else getattr(annotations, "requires_approval", None)
    )
    return bool(value)


class SkillMapper:
    """Converts apcore ModuleDescriptor to a2a.types.AgentSkill."""

    def __init__(self, schema_converter: SchemaConverter | None = None) -> None:
        # Share root-type detection with SchemaConverter so the "string root"
        # rule lives in exactly one place.
        self._schema_converter = schema_converter or SchemaConverter()

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
        _append_annotation_tags(resolved_tags, descriptor)

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

        if self._schema_converter.detect_root_type(schema) == "string":
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
