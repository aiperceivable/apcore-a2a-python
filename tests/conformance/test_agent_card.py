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
from google.protobuf.json_format import MessageToDict

from apcore_a2a.adapters.agent_card import AgentCardBuilder
from apcore_a2a.adapters.skill_mapper import SkillMapper

from ._spec import load_fixture, partial_match

_FIXTURE = load_fixture("agent_card.json")


class _Descriptor:
    def __init__(self, spec: dict[str, Any]) -> None:
        self.module_id = spec["module_id"]
        self.description = spec["description"]
        self.tags: list[str] = list(spec.get("tags") or [])
        self.examples: list[Any] = []
        self.input_schema: dict[str, Any] = {}
        self.output_schema: dict[str, Any] = {}
        # A plain dict, which is what `_append_annotation_tags` reads when the
        # descriptor came from a source that does not build ModuleAnnotations.
        self.annotations = spec.get("annotations")


def _registry_for(modules: list[dict[str, Any]]) -> Any:
    descriptors = {m["module_id"]: _Descriptor(m) for m in modules}
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
    if "card_variant" in spec:
        # Cases carrying card_variant / acl_rules / identity exercise the
        # serve() layer (the anonymous-principal filter needs the executor's
        # ACL), not AgentCardBuilder.build. tests/server/test_card_visibility.py
        # asserts those against a real app.
        pytest.skip("serve()-layer case; covered by test_card_visibility.py")
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

    # srs FR-SKL-004: apcore's behavioral annotations reach the wire as
    # namespaced tags, in a fixed order, after the module's own tags.
    for skill_id, expected_tags in case.get("expected_skill_tags", {}).items():
        skill = next((s for s in actual.get("skills", []) if s.get("id") == skill_id), None)
        assert skill is not None, f"[{case['id']}] no skill {skill_id!r} on the card"
        # proto3 omits an empty repeated field on the wire; absent == [].
        assert skill.get("tags", []) == expected_tags, f"[{case['id']}] tags for {skill_id}"

    if "expected_skill_ids" in case:
        # Which skills appear is the contract; the order the registry
        # enumerates them in is not.
        actual_ids = sorted(s.get("id") for s in actual.get("skills", []))
        assert actual_ids == sorted(case["expected_skill_ids"]), f"[{case['id']}] skill ids"

    if case.get("expected_security_requirements_empty"):
        # proto3 omits an empty repeated field on the wire; absent == empty.
        assert actual.get("securityRequirements", []) == [], f"[{case['id']}] securityRequirements not empty"

    if case.get("expected_security_schemes_empty"):
        # Representation-tolerant: proto3 omits the empty map (Python) while the
        # TS object emits {}. Both mean "no security schemes".
        assert not actual.get("securitySchemes"), f"[{case['id']}] securitySchemes not empty"
