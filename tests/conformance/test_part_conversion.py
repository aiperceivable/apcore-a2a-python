"""Conformance — Algorithm A-PART: Part <-> module input/output parity.

Fixture: ``conformance/fixtures/part_conversion.json`` (shared verbatim with the
TypeScript and Rust runners). Drives :class:`PartConverter` directly.
"""

from __future__ import annotations

from typing import Any

import pytest
from a2a.types import Part
from google.protobuf import struct_pb2
from google.protobuf.json_format import MessageToDict, ParseDict

from apcore_a2a.adapters.parts import PartConverter

from ._spec import load_fixture, partial_match

_FIXTURE = load_fixture("part_conversion.json")


class _Descriptor:
    """Minimal duck-typed descriptor exposing ``input_schema``."""

    def __init__(self, input_schema: Any) -> None:
        self.input_schema = input_schema


def _build_part(spec: dict[str, Any]) -> Part:
    if "text" in spec:
        return Part(text=spec["text"])
    if "data" in spec:
        return Part(data=ParseDict(spec["data"], struct_pb2.Value()))
    if "url" in spec:
        return Part(url=spec["url"])
    if "raw" in spec:
        return Part(raw=spec["raw"])
    raise AssertionError(f"unrecognized part spec: {spec}")


@pytest.mark.parametrize(
    "case",
    _FIXTURE["test_cases"],
    ids=[c["id"] for c in _FIXTURE["test_cases"]],
)
def test_part_conversion_ok(case: dict[str, Any]) -> None:
    conv = PartConverter()
    if case["direction"] == "output_to_parts":
        artifact = conv.output_to_parts(case["input"], case.get("task_id", ""))
        actual = MessageToDict(artifact)
        if "expected_artifact_id" in case:
            assert actual.get("artifactId") == case["expected_artifact_id"], f"[{case['id']}] {actual}"
        err = partial_match(case["expected_parts"], actual.get("parts", []))
        assert err is None, f"[{case['id']}] {err}"
    else:  # parts_to_input
        parts = [_build_part(p) for p in case["parts"]]
        result = conv.parts_to_input(parts, _Descriptor(case.get("input_schema")))
        expected = case["expected_input"]
        if isinstance(expected, dict | list):
            err = partial_match(expected, result)
            assert err is None, f"[{case['id']}] {err}"
        else:
            assert result == expected, f"[{case['id']}] got {result!r}"


@pytest.mark.parametrize(
    "case",
    _FIXTURE["error_cases"],
    ids=[c["id"] for c in _FIXTURE["error_cases"]],
)
def test_part_conversion_errors(case: dict[str, Any]) -> None:
    conv = PartConverter()
    parts = [_build_part(p) for p in case["parts"]]
    with pytest.raises(Exception) as exc_info:  # noqa: PT011 - message asserted below
        conv.parts_to_input(parts, _Descriptor(case.get("input_schema")))
    message = str(exc_info.value)
    for needle in case.get("expected_error_message", []):
        assert needle in message, f"[{case['id']}] missing {needle!r} in {message!r}"
