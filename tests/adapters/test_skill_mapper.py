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
    skill = mapper.to_skill(simple_descriptor)
    assert skill.tags == ["image", "transform"]


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


# --- _build_extensions ---

def test_build_extensions_returns_none_when_annotations_none(mapper):
    assert mapper._build_extensions(None) is None


def test_build_extensions_returns_apcore_dict(mapper):
    class Annotations:
        readonly = True
        destructive = False
        idempotent = True
        requires_approval = False
        open_world = False

    result = mapper._build_extensions(Annotations())
    assert result is not None
    assert "apcore" in result
    assert result["apcore"]["annotations"]["readonly"] is True
    assert result["apcore"]["annotations"]["idempotent"] is True
    assert result["apcore"]["annotations"]["open_world"] is False


def test_build_extensions_defaults_missing_attrs(mapper):
    class EmptyAnnotations:
        pass

    result = mapper._build_extensions(EmptyAnnotations())
    assert result is not None
    ann = result["apcore"]["annotations"]
    assert ann["readonly"] is False
    assert ann["destructive"] is False
    assert ann["open_world"] is True  # default True
