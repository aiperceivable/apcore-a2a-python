"""Tests for SchemaConverter."""
import pytest
from apcore_a2a.adapters.schema import SchemaConverter
from tests.conftest import ModuleDescriptor


@pytest.fixture
def converter():
    return SchemaConverter()


# convert_input_schema

def test_none_schema_returns_empty_object(converter):
    desc = ModuleDescriptor(input_schema=None)
    result = converter.convert_input_schema(desc)
    assert result == {"type": "object", "properties": {}}


def test_empty_dict_schema_returns_empty_object(converter):
    desc = ModuleDescriptor(input_schema={})
    result = converter.convert_input_schema(desc)
    assert result == {"type": "object", "properties": {}}


def test_flat_schema_preserved(converter):
    schema = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}
    desc = ModuleDescriptor(input_schema=schema)
    result = converter.convert_input_schema(desc)
    assert result["properties"]["x"]["type"] == "integer"
    assert result["required"] == ["x"]


def test_does_not_modify_original(converter):
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    original = {"type": "object", "properties": {"x": {"type": "string"}}}
    desc = ModuleDescriptor(input_schema=schema)
    converter.convert_input_schema(desc)
    assert schema == original


def test_refs_inlined(converter):
    schema = {
        "type": "object",
        "$defs": {"Item": {"type": "object", "properties": {"name": {"type": "string"}}}},
        "properties": {"item": {"$ref": "#/$defs/Item"}},
    }
    desc = ModuleDescriptor(input_schema=schema)
    result = converter.convert_input_schema(desc)
    assert "$defs" not in result
    assert "$ref" not in str(result)
    assert result["properties"]["item"]["properties"]["name"]["type"] == "string"


def test_defs_removed_from_output(converter):
    schema = {
        "$defs": {"X": {"type": "string"}},
        "properties": {"x": {"$ref": "#/$defs/X"}},
    }
    desc = ModuleDescriptor(input_schema=schema)
    result = converter.convert_input_schema(desc)
    assert "$defs" not in result


def test_schema_without_type_gets_object(converter):
    schema = {"properties": {"name": {"type": "string"}}}
    desc = ModuleDescriptor(input_schema=schema)
    result = converter.convert_input_schema(desc)
    assert result["type"] == "object"


# convert_output_schema

def test_output_none_schema(converter):
    desc = ModuleDescriptor(output_schema=None)
    result = converter.convert_output_schema(desc)
    assert result == {"type": "object", "properties": {}}


def test_output_preserves_schema(converter):
    schema = {"type": "object", "properties": {"result": {"type": "string"}}}
    desc = ModuleDescriptor(output_schema=schema)
    result = converter.convert_output_schema(desc)
    assert result["properties"]["result"]["type"] == "string"
