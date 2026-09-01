"""Tests for SkillMapper."""

import pytest
from a2a.types import AgentSkill

from apcore_a2a.adapters.skill_mapper import SkillMapper
from tests.conftest import ModuleDescriptor, ModuleExample


@pytest.fixture
def mapper():
    return SkillMapper()


def test_returns_agent_skill_model(mapper, simple_descriptor):
    skill = mapper.to_skill(simple_descriptor)
    assert isinstance(skill, AgentSkill)


def test_id_set(mapper, simple_descriptor):
    skill = mapper.to_skill(simple_descriptor)
    assert skill.id == "image.resize"


def test_name_humanized(mapper, simple_descriptor):
    skill = mapper.to_skill(simple_descriptor)
    assert skill.name == "Image Resize"


def test_description_preserved(mapper, simple_descriptor):
    skill = mapper.to_skill(simple_descriptor)
    assert skill.description == simple_descriptor.description


def test_tags_preserved(mapper, simple_descriptor):
    """The module's own tags stay first and in order; annotations are appended."""
    skill = mapper.to_skill(simple_descriptor)
    assert skill.tags[:2] == ["image", "transform"]


def test_annotations_reach_the_wire_as_namespaced_tags(mapper, simple_descriptor):
    """srs FR-SKL-004. A2A 1.0 AgentSkill has no extensions and no metadata
    member — and here the type is generated from the A2A protobuf schema — so
    tags is the only carrier that exists."""
    skill = mapper.to_skill(simple_descriptor)  # readonly=True, idempotent=True
    assert list(skill.tags) == ["image", "transform", "apcore:readonly", "apcore:idempotent"]


def test_annotation_tag_order_is_fixed(mapper, destructive_descriptor):
    """Fixed order so the card is byte-identical across the three bindings."""
    skill = mapper.to_skill(destructive_descriptor)  # destructive + requires_approval
    assert list(skill.tags) == ["file", "dangerous", "apcore:destructive", "apcore:requires-approval"]


def test_unset_annotations_emit_no_tags(mapper, no_annotations_descriptor):
    """Absence means "not asserted", never "asserted False" — matching how the
    apcore MCP binding maps the same annotations onto optional hints."""
    skill = mapper.to_skill(no_annotations_descriptor)
    assert [t for t in skill.tags if t.startswith("apcore:")] == []


def test_input_modes_object_schema(mapper, simple_descriptor):
    skill = mapper.to_skill(simple_descriptor)
    assert "application/json" in skill.input_modes


def test_output_modes_with_schema(mapper, simple_descriptor):
    skill = mapper.to_skill(simple_descriptor)
    assert "application/json" in skill.output_modes


def test_input_modes_no_schema(mapper, empty_schema_descriptor):
    skill = mapper.to_skill(empty_schema_descriptor)
    assert skill.input_modes == ["text/plain"]


def test_output_modes_no_schema(mapper, empty_schema_descriptor):
    skill = mapper.to_skill(empty_schema_descriptor)
    assert skill.output_modes == ["text/plain"]


def test_examples_included(mapper, simple_descriptor):
    skill = mapper.to_skill(simple_descriptor)
    assert len(skill.examples) == 1
    assert isinstance(skill.examples[0], str)


def test_examples_capped_at_10(mapper):
    desc = ModuleDescriptor(
        module_id="test.module",
        description="Test",
        examples=[ModuleExample(title=f"ex{i}", inputs={"i": i}) for i in range(15)],
    )
    skill = mapper.to_skill(desc)
    assert len(skill.examples) == 10


def test_no_description_returns_none(mapper):
    desc = ModuleDescriptor(module_id="no.desc", description="")
    assert mapper.to_skill(desc) is None


def test_humanize_underscore(mapper):
    desc = ModuleDescriptor(module_id="text_process.clean_up", description="Test")
    skill = mapper.to_skill(desc)
    assert skill.name == "Text Process Clean Up"


def test_humanize_single_word(mapper):
    desc = ModuleDescriptor(module_id="ping", description="Test")
    skill = mapper.to_skill(desc)
    assert skill.name == "Ping"


# --- Empty-string fallthrough (cross-language parity) ---


def test_empty_string_alias_falls_through(mapper):
    desc = ModuleDescriptor(
        module_id="image.resize",
        description="Resize an image",
        metadata={"display": {"a2a": {"alias": ""}, "alias": ""}},
    )
    skill = mapper.to_skill(desc)
    assert skill.name == "Image Resize"


def test_empty_string_description_falls_through(mapper):
    desc = ModuleDescriptor(
        module_id="image.resize",
        description="Resize an image",
        metadata={"display": {"a2a": {"description": ""}, "description": ""}},
    )
    skill = mapper.to_skill(desc)
    assert skill.description == "Resize an image"


def test_empty_string_guidance_not_appended(mapper):
    desc = ModuleDescriptor(
        module_id="image.resize",
        description="Resize an image",
        metadata={"display": {"a2a": {"guidance": ""}}},
    )
    skill = mapper.to_skill(desc)
    assert skill.description == "Resize an image"
