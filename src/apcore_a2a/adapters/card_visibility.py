"""Agent Card skill visibility — who gets to see which skills.

apcore's ACL is the authority on who may invoke what, and the discovery surface
reflects that authority rather than ignoring it. Two surfaces, two answers:

- the **public** card (srs FR-AGC-003) answers "what may *anyone* call": every
  registered skill, minus those the ACL denies to the anonymous principal, minus
  those annotated ``requires_approval``. It resolves exactly one identity, so it
  is computed once when the card is built. A per-caller filter here would be
  strictly more accurate and unaffordable: ``/.well-known/`` is auth-exempt by
  design, so every anonymous request would drive ``len(skills)`` calls into the
  consumer's ACL audit sink, each recording a ``deny`` decision indistinguishable
  from a real enforcement event, at whatever rate the client chooses.

- the **extended** card (srs FR-AGC-004) answers "what may *you* call": the ACL
  resolved against the authenticated identity, with ``requires_approval`` skills
  restored — an approval gate is a prompt the caller can satisfy, not a refusal.
  Affordable precisely because this endpoint requires credentials.

Authorization and approval are two independent results, not one (apcore
PROTOCOL_SPEC §6.1.6), and this module reads them apart. ``ACL.check`` folds
them into a boolean that **fails closed** on an approval requirement — correct
for a caller about to execute, wrong for a discovery surface, where it would
delete a skill from the extended card for the one reason FR-AGC-004 says to keep
it. ``ACL.check_access`` carries both axes, so ``access`` decides visibility and
``approval_required`` decides only whether the public card is the right surface.

Before this module, this binding filtered nothing at all: ``_build_skills``
iterated ``registry.list()`` and never consulted the ACL, so a module the ACL
denied to everyone was still advertised — by id, name, description and full
input schema — to any anonymous caller.
"""

from __future__ import annotations

import logging
from typing import Any

from a2a.types import AgentCard

from apcore_a2a.adapters.skill_mapper import requires_approval

logger = logging.getLogger(__name__)


def executor_acl(executor: Any) -> Any | None:
    """The apcore ACL backing ``executor``, if one is configured.

    apcore-python exposes ``set_acl`` but no getter, so this reads the public
    attribute when one appears upstream and falls back to the private field.
    Returning ``None`` means "no ACL configured", which is the common case and
    leaves every card unfiltered.
    """
    for attribute in ("acl", "_acl"):
        acl = getattr(executor, attribute, None)
        if acl is not None and hasattr(acl, "check"):
            return acl
    return None


def _acl_context(identity: Any | None) -> Any | None:
    """An apcore ``Context`` carrying ``identity``, for conditional ACL rules.

    An ACL rule's ``conditions`` block (``identity_types``, ``roles``) is
    evaluated against the context, and ``check_conditions`` returns ``False``
    without one — so a card filtered with no context would hide every skill a
    conditional rule allows. Building the context the same way the executor does
    is what keeps the card and the call path agreeing about the same principal.
    """
    try:
        from apcore import Context  # type: ignore[import]

        return Context.create(identity=identity)
    except Exception:  # pragma: no cover - apcore always provides Context
        logger.debug("could not build an apcore Context for ACL filtering", exc_info=True)
        return None


def _decide(acl: Any, caller_id: str | None, skill_id: str, ctx: Any | None) -> tuple[bool, bool]:
    """``(authorized, approval_required)`` for one skill, from apcore's ACL.

    Reads ``check_access`` (apcore >= 0.28.0, PROTOCOL_SPEC §6.8.1), which
    reports the two axes separately. The ``check`` fallback exists for an ACL
    that predates the accessor: there ``approval`` did not exist as a rule
    field, so ``False`` is not a guess but the only value such an ACL can mean —
    and a boolean that already fails closed degrades this surface toward showing
    less, never more.
    """
    check_access = getattr(acl, "check_access", None)
    if check_access is None:
        return bool(acl.check(caller_id, skill_id, ctx)), False
    decision = check_access(caller_id, skill_id, ctx)
    return decision.access == "allow", bool(decision.approval_required)


def skill_access(executor: Any, skill_ids: list[str], identity: Any | None) -> dict[str, bool]:
    """The skills the ACL permits ``identity`` to invoke, each mapped to whether
    invoking it needs a human first.

    With no ACL configured every id is permitted and none is gated, which is what
    makes this free for the common single-tenant deployment.

    The ACL is consulted with **no arguments projection**, because a card is
    discovery and there is no call site yet. An ``arguments`` condition (§6.1.7)
    is therefore unevaluable, so a rule carrying one neither denies nor grants —
    but an ``allow`` rule's ``approval: required`` stays *pending* and composes
    with whatever grants (§6.1.1 rule 5). A skill gated only for some argument
    shapes thus reports ``True`` here: at discovery time "this may need approval"
    is the honest answer, and it is the one that keeps such a skill off the
    public card.

    ``caller_id`` is left ``None`` deliberately. apcore defines it as the
    *calling module* in a nested call chain, managed by ``Context.child``; a
    top-level inbound request has none, and the ACL maps ``None`` to
    ``@external``. That is apcore's contract, not a gap — ``callers:
    ["@external"]`` is how an operator denies external access, and it has to keep
    matching an authenticated request or the rule silently stops covering the
    traffic it was written for. The authenticated principal travels in the
    context instead, where the ``identity_types`` / ``roles`` conditions see it.
    """
    acl = executor_acl(executor)
    if acl is None:
        return {skill_id: False for skill_id in skill_ids}
    base = _acl_context(identity)
    access: dict[str, bool] = {}
    for skill_id in skill_ids:
        ctx = base.child(skill_id) if base is not None else None
        caller_id = getattr(ctx, "caller_id", None) if ctx is not None else None
        try:
            authorized, approval_required = _decide(acl, caller_id, skill_id, ctx)
        except Exception:  # pragma: no cover - a broken ACL must not serve MORE
            logger.warning("ACL check raised for skill %s; withholding it", skill_id)
            continue
        if authorized:
            access[skill_id] = approval_required
    return access


def allowed_skill_ids(executor: Any, skill_ids: list[str], identity: Any | None) -> set[str]:
    """The subset of ``skill_ids`` the ACL authorizes ``identity`` to invoke.

    The authorization axis alone: a skill the ACL allows but gates behind an
    approval is in this set, because the caller may reach it. Callers that also
    need the gate read :func:`skill_access`.
    """
    return set(skill_access(executor, skill_ids, identity))


def _card_with_skills(card: AgentCard, keep: set[str]) -> AgentCard:
    """A copy of ``card`` carrying only the skills whose id is in ``keep``."""
    filtered = AgentCard()
    filtered.CopyFrom(card)
    kept = [skill for skill in card.skills if skill.id in keep]
    del filtered.skills[:]
    filtered.skills.extend(kept)
    return filtered


def build_public_card(card: AgentCard, executor: Any, registry: Any) -> AgentCard:
    """The public card: what an unauthenticated caller could actually invoke.

    See the module docstring for why this is resolved once rather than per
    caller (srs FR-AGC-003).
    """
    ids = [skill.id for skill in card.skills]
    access = skill_access(executor, ids, identity=None)
    # Both sources of an approval gate, unioned as PROTOCOL_SPEC §6.9 composes
    # them: the module's own annotation, and an ACL rule carrying
    # ``approval: required`` for this principal. Since apcore 0.28.0 the
    # annotation is one source among several, so reading it alone would leave a
    # skill on the public card that an anonymous caller cannot in fact just call.
    keep = {skill_id for skill_id, approval_required in access.items() if not approval_required}
    for skill_id in list(keep):
        descriptor = registry.get_definition(skill_id) if registry is not None else None
        if descriptor is not None and requires_approval(descriptor):
            keep.discard(skill_id)
    return _card_with_skills(card, keep)


def build_extended_card(card: AgentCard, executor: Any, identity: Any | None) -> AgentCard:
    """The extended card: what the authenticated caller may invoke.

    ``requires_approval`` skills are kept (srs FR-AGC-004 criterion 2), whether
    the gate comes from the module's annotation or from an ACL rule. Only the
    authorization axis of the decision filters here — dropping a skill because it
    needs a human would report a refusal the ACL never issued.
    """
    ids = [skill.id for skill in card.skills]
    return _card_with_skills(card, allowed_skill_ids(executor, ids, identity))
