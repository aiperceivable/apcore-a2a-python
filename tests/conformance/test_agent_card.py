"""Conformance — Algorithm A-CARD: Agent Card builder-level wire-shape parity.

Fixture: ``conformance/fixtures/agent_card.json`` (shared verbatim with the
TypeScript and Rust runners). Builds an AgentCard via :class:`AgentCardBuilder`,
serializes to the A2A 1.0 JSON wire form (camelCase, defaults omitted), and
partial-matches the expected shape — chiefly the securitySchemes proto3 oneof
form and supportedInterfaces (no top-level url).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from a2a.types import AgentCapabilities
from apcore_a2a.adapters.agent_card import AgentCardBuilder
from apcore_a2a.adapters.skill_mapper import SkillMapper
from google.protobuf.json_format import MessageToDict

from ._spec import load_fixture, partial_match

_FIXTURE = load_fixture("agent_card.json")


class _Descriptor:
    def __init__(self, module_id: str, description: str) -> None:
        self.module_id = module_id
        self.description = description
        self.tags: list[str] = []
        self.examples: list[Any] = []
        self.input_schema: dict[str, Any] = {}
        self.output_schema: dict[str, Any] = {}
        self.annotations = None


def _registry_for(modules: list[dict[str, Any]]) -> Any:
    descriptors = {m["module_id"]: _Descriptor(m["module_id"], m["description"]) for m in modules}
    registry = MagicMock()
    registry.list.return_value = list(descriptors.keys())
    registry.get_definition.side_effect = descriptors.get
    return registry


@pytest.mark.parametrize(
    "case",
    _FIXTURE["test_cases"],
    ids=[c["id"] for c in _FIXTURE["test_cases"]],
)
def test_agent_card_shape(case: dict[str, Any]) -> None:
    spec = case["input"]
    builder = AgentCardBuilder(SkillMapper())
    card = builder.build(
        _registry_for(spec["modules"]),
        name=spec["name"],
        description=spec["description"],
        version=spec["version"],
        url=spec["url"],
        capabilities=AgentCapabilities(streaming=False, push_notifications=False),
        security_schemes=spec.get("security_schemes_input"),
    )
    actual = MessageToDict(card)

    if "expected_card" in case:
        err = partial_match(case["expected_card"], actual)
        assert err is None, f"[{case['id']}] {err}"

    for absent in case.get("expected_card_absent_keys", []):
        assert absent not in actual, f"[{case['id']}] unexpected key {absent!r} in card"

    if "expected_skill_count" in case:
        assert len(actual.get("skills", [])) == case["expected_skill_count"], f"[{case['id']}] skill count"

    if case.get("expected_security_requirements_empty"):
        # proto3 omits an empty repeated field on the wire; absent == empty.
        assert actual.get("securityRequirements", []) == [], f"[{case['id']}] securityRequirements not empty"

    if case.get("expected_security_schemes_empty"):
        # Representation-tolerant: proto3 omits the empty map (Python) while the
        # TS object emits {}. Both mean "no security schemes".
        assert not actual.get("securitySchemes"), f"[{case['id']}] securitySchemes not empty"
