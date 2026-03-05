"""Tests for PartConverter."""
import pytest
from a2a.types import Artifact, DataPart, Part, TextPart
from apcore_a2a.adapters.parts import PartConverter
from apcore_a2a.adapters.schema import SchemaConverter


@pytest.fixture
def converter():
    return PartConverter(SchemaConverter())


class FakeDesc:
    pass


def _text_part(text: str) -> Part:
    return Part(root=TextPart(text=text))


def _data_part(data: dict) -> Part:
    return Part(root=DataPart(data=data))


# parts_to_input

def test_text_part_returns_string(converter):
    parts = [_text_part("resize to 800x600")]
    result = converter.parts_to_input(parts, FakeDesc())
    assert result == "resize to 800x600"


def test_data_part_returns_dict(converter):
    parts = [_data_part({"width": 800, "height": 600})]
    result = converter.parts_to_input(parts, FakeDesc())
    assert result == {"width": 800, "height": 600}


def test_empty_parts_raises(converter):
    with pytest.raises((ValueError, IndexError)):
        converter.parts_to_input([], FakeDesc())


def test_multiple_parts_raises(converter):
    parts = [_text_part("a"), _text_part("b")]
    with pytest.raises(ValueError):
        converter.parts_to_input(parts, FakeDesc())


# output_to_parts

def test_string_output_returns_artifact_with_text_part(converter):
    artifact = converter.output_to_parts("hello world")
    assert isinstance(artifact, Artifact)
    assert len(artifact.parts) == 1
    assert isinstance(artifact.parts[0].root, TextPart)
    assert artifact.parts[0].root.text == "hello world"


def test_dict_output_returns_artifact_with_data_part(converter):
    artifact = converter.output_to_parts({"width": 800})
    assert isinstance(artifact, Artifact)
    assert len(artifact.parts) == 1
    assert isinstance(artifact.parts[0].root, DataPart)
    assert artifact.parts[0].root.data == {"width": 800}


def test_none_output_returns_empty_artifact(converter):
    artifact = converter.output_to_parts(None)
    assert isinstance(artifact, Artifact)
    assert artifact.parts == []


def test_int_output_returns_text_part(converter):
    artifact = converter.output_to_parts(42)
    assert isinstance(artifact.parts[0].root, TextPart)
    assert "42" in artifact.parts[0].root.text


def test_artifact_id_uses_task_id(converter):
    artifact = converter.output_to_parts("out", task_id="task-123")
    assert "task-123" in artifact.artifact_id


def test_list_output_returns_json_text_part(converter):
    """T3: list output must serialize as JSON, not Python repr."""
    artifact = converter.output_to_parts([1, 2, 3])
    assert isinstance(artifact, Artifact)
    assert len(artifact.parts) == 1
    root = artifact.parts[0].root
    assert isinstance(root, TextPart)
    import json
    assert json.loads(root.text) == [1, 2, 3]


def test_list_output_not_python_repr(converter):
    """list output must not contain Python repr brackets like \"[1, 2, 3]\" with spaces."""
    artifact = converter.output_to_parts(["a", "b"])
    text = artifact.parts[0].root.text
    # JSON uses double quotes; Python repr uses single quotes
    import json
    parsed = json.loads(text)
    assert parsed == ["a", "b"]
