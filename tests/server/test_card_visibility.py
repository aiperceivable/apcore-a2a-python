"""Agent Card skill visibility — srs FR-AGC-003 / FR-AGC-004 / FR-AGC-006.

Covers the fixture cases in ``conformance/fixtures/agent_card.json`` that carry
``card_variant``: they need the executor's ACL, so they exercise the serve()
layer rather than ``AgentCardBuilder.build`` and the shared conformance runner
skips them.

Before this behaviour existed, ``_build_skills`` iterated ``registry.list()``
and consulted the ACL nowhere, so a module the ACL denied to everyone was still
advertised — by id, name, description and full input schema — to any anonymous
caller. ``/.well-known/`` is auth-exempt by design, so no credential stood in
the way.
"""

from __future__ import annotations

from typing import Any

import pytest
from apcore.acl import ACL, ACLRule
from apcore.context import Identity

from apcore_a2a.adapters.agent_card import AgentCardBuilder
from apcore_a2a.adapters.card_visibility import build_extended_card, build_public_card
from apcore_a2a.adapters.skill_mapper import SkillMapper


class _Annotations:
    def __init__(self, **flags: bool) -> None:
        self.readonly = flags.get("readonly", False)
        self.destructive = flags.get("destructive", False)
        self.idempotent = flags.get("idempotent", False)
        self.requires_approval = flags.get("requires_approval", False)


class _Descriptor:
    def __init__(self, module_id: str, description: str, annotations: Any = None) -> None:
        self.module_id = module_id
        self.description = description
        self.tags: list[str] = []
        self.examples: list[Any] = []
        self.input_schema: dict[str, Any] = {}
        self.output_schema: dict[str, Any] = {}
        self.annotations = annotations


class _Registry:
    def __init__(self, descriptors: dict[str, _Descriptor]) -> None:
        self._descriptors = descriptors

    def list(self) -> list[str]:
        return list(self._descriptors)

    def get_definition(self, module_id: str) -> _Descriptor | None:
        return self._descriptors.get(module_id)


class _Executor:
    """The minimum surface :mod:`card_visibility` reads off an apcore Executor."""

    def __init__(self, acl: ACL | None = None) -> None:
        self._acl = acl


def _card(registry: _Registry):
    from a2a.types import AgentCapabilities

    return AgentCardBuilder(SkillMapper()).build(
        registry,
        name="agent",
        description="d",
        version="1.0.0",
        url="http://localhost:8000",
        capabilities=AgentCapabilities(streaming=False, push_notifications=False),
    )


@pytest.fixture
def gated_registry() -> _Registry:
    return _Registry(
        {
            "math.add": _Descriptor("math.add", "Adds"),
            "admin.users.delete": _Descriptor(
                "admin.users.delete",
                "Deletes a user",
                _Annotations(requires_approval=True, destructive=True),
            ),
        }
    )


def _ids(card) -> list[str]:
    return sorted(skill.id for skill in card.skills)


def test_public_card_hides_requires_approval_even_without_an_acl(gated_registry):
    """srs FR-AGC-003 criterion 7. An approval gate is the operator saying "a
    human decides each of these" — not something to advertise anonymously, and
    withholding it is what leaves the extended card something to carry."""
    card = _card(gated_registry)
    public = build_public_card(card, _Executor(), gated_registry)
    assert _ids(public) == ["math.add"]


def test_extended_card_restores_requires_approval(gated_registry):
    """srs FR-AGC-004 criterion 2 and 9: not a copy of the public card."""
    card = _card(gated_registry)
    public = build_public_card(card, _Executor(), gated_registry)
    extended = build_extended_card(card, _Executor(), Identity(id="u1", type="service"))
    assert _ids(extended) == ["admin.users.delete", "math.add"]
    assert _ids(public) != _ids(extended)


def test_public_card_hides_skills_the_acl_denies_to_anonymous():
    """srs FR-AGC-003 criterion 6."""
    registry = _Registry(
        {
            "math.add": _Descriptor("math.add", "Adds"),
            "admin.reindex": _Descriptor("admin.reindex", "Reindexes"),
        }
    )
    acl = ACL(
        rules=[ACLRule(callers=["@external"], targets=["admin.*"], effect="deny")],
        default_effect="allow",
    )
    public = build_public_card(_card(registry), _Executor(acl), registry)
    assert _ids(public) == ["math.add"]


def test_a_conditional_rule_is_evaluated_against_the_callers_identity():
    """The card filter must build an apcore Context, or every skill a
    conditional rule allows would be hidden: ``check_conditions`` returns False
    without one, so a context-less filter and the enforcement path would
    disagree about the same principal."""
    registry = _Registry({"math.add": _Descriptor("math.add", "Adds")})
    acl = ACL(
        rules=[
            ACLRule(
                callers=["*"],
                targets=["*"],
                effect="allow",
                conditions={"identity_types": ["service"]},
            )
        ],
        default_effect="deny",
    )
    card = _card(registry)
    trusted = build_extended_card(card, _Executor(acl), Identity(id="u1", type="service"))
    untrusted = build_extended_card(card, _Executor(acl), Identity(id="u2", type="untrusted"))
    anonymous = build_public_card(card, _Executor(acl), registry)
    assert _ids(trusted) == ["math.add"]
    assert _ids(untrusted) == []
    assert _ids(anonymous) == []


def test_no_acl_configured_leaves_the_card_unfiltered():
    """The common single-tenant case must cost nothing and hide nothing."""
    registry = _Registry(
        {
            "math.add": _Descriptor("math.add", "Adds"),
            "admin.reindex": _Descriptor("admin.reindex", "Reindexes"),
        }
    )
    public = build_public_card(_card(registry), _Executor(), registry)
    assert _ids(public) == ["admin.reindex", "math.add"]


def test_a_raising_acl_withholds_the_skill_rather_than_serving_it():
    """A broken ACL must fail closed: serving MORE than the policy allows is the
    one outcome that cannot be walked back."""

    class _BrokenACL:
        def check(self, caller_id, target_id, context=None):
            raise RuntimeError("audit sink is down")

    registry = _Registry({"math.add": _Descriptor("math.add", "Adds")})
    public = build_public_card(_card(registry), _Executor(_BrokenACL()), registry)
    assert _ids(public) == []


def test_an_acl_approval_gate_hides_the_skill_from_the_public_card_only():
    """apcore 0.28.0 (PROTOCOL_SPEC §6.1.6) lets an ACL rule require a human
    without denying the call, and §6.9 composes that with the module annotation
    by union. A skill the operator gated that way is not something an anonymous
    caller can just call, so it leaves the public card exactly as an annotated
    one does — and it stays on the extended card, because the caller *is*
    authorized: the gate is a prompt they can satisfy, not a refusal.

    The regression this pins is the fold: ``ACL.check`` collapses the two axes
    and returns False for allow-with-approval, so a filter written against the
    boolean would delete the skill from **both** cards, reporting a refusal the
    ACL never issued.
    """
    registry = _Registry(
        {
            "math.add": _Descriptor("math.add", "Adds"),
            "vcs.push": _Descriptor("vcs.push", "Pushes"),
        }
    )
    acl = ACL(
        rules=[
            ACLRule(callers=["*"], targets=["vcs.push"], effect="allow", approval="required"),
            ACLRule(callers=["*"], targets=["*"], effect="allow"),
        ],
        default_effect="deny",
    )
    card = _card(registry)
    public = build_public_card(card, _Executor(acl), registry)
    extended = build_extended_card(card, _Executor(acl), Identity(id="u1", type="service"))
    assert _ids(public) == ["math.add"]
    assert _ids(extended) == ["math.add", "vcs.push"]


def test_an_acl_denial_still_hides_the_skill_from_both_cards():
    """The approval axis must not have loosened the authorization one: a denied
    skill is absent from the extended card too, however the decision was
    reached."""
    registry = _Registry({"math.add": _Descriptor("math.add", "Adds")})
    acl = ACL(
        rules=[ACLRule(callers=["*"], targets=["math.add"], effect="deny")],
        default_effect="allow",
    )
    card = _card(registry)
    assert _ids(build_public_card(card, _Executor(acl), registry)) == []
    assert _ids(build_extended_card(card, _Executor(acl), Identity(id="u1", type="service"))) == []
