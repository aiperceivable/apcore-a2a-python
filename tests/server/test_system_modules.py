"""apcore's `system.*` management namespace — srs FR-AGC-003 (12, 13), FR-AGC-004
(11), FR-AGC-007. Resolves `aiperceivable/apcore-a2a` issue #5.

Two defects, deliberately fixed together. `sys_modules=True` registered nothing —
the factory built the registration `Config` as `{"apcore": {"sys_modules": ...}}`
while apcore reads `config.get("sys_modules.enabled")` in legacy mode, so
`register_sys_modules` returned at its first line and the success log lied. And
had that config path been repaired on its own, the six read modules would have
started publishing the deployment's module inventory, health and usage to any
anonymous caller, because `/.well-known/` is auth-exempt and a deployment without
an `acl/` directory has no ACL at all.
"""

from __future__ import annotations

import logging

import pytest
from apcore import Registry
from apcore.decorator import module as apcore_module
from apcore.executor import Executor

from apcore_a2a.server.factory import A2AServerFactory


@pytest.fixture
def registry_with_a_user_module() -> Registry:
    registry = Registry()

    @apcore_module(id="math.add", description="Adds two numbers", registry=registry)
    def add(a: int, b: int) -> int:
        return a + b

    return registry


def _create(registry: Registry, executor: Executor, **kwargs):
    return A2AServerFactory().create(
        registry,
        executor,
        name="agent",
        description="d",
        version="1.0.0",
        url="http://localhost:8000",
        **kwargs,
    )


def test_sys_modules_true_actually_registers_the_system_modules(registry_with_a_user_module):
    """The bug this pins: the flag was a silent no-op in every deployment."""
    registry = registry_with_a_user_module
    executor = Executor(registry)
    _create(registry, executor, sys_modules=True)
    registered = sorted(m for m in registry.list() if m.startswith("system."))
    assert registered, "sys_modules=True must register apcore's system.* modules"
    assert "system.health.summary" in registered
    assert "system.manifest.full" in registered


def test_sys_modules_false_registers_nothing(registry_with_a_user_module):
    registry = registry_with_a_user_module
    executor = Executor(registry)
    _create(registry, executor, sys_modules=False)
    assert [m for m in registry.list() if m.startswith("system.")] == []


def test_registered_system_modules_stay_off_the_public_card(registry_with_a_user_module):
    """srs FR-AGC-003 criteria 12 and 13, end to end and with no ACL configured —
    which is the state of every deployment without an `acl/` directory."""
    registry = registry_with_a_user_module
    executor = Executor(registry)
    _, card = _create(registry, executor, sys_modules=True)
    assert [m for m in registry.list() if m.startswith("system.")], "precondition"
    assert [skill.id for skill in card.skills] == ["math.add"]


def test_no_warning_when_no_control_surface_is_registered(registry_with_a_user_module, caplog):
    """srs FR-AGC-007 criterion 3. The read modules alone are not a control
    surface, so the single opt-in must stay quiet."""
    registry = registry_with_a_user_module
    executor = Executor(registry)
    with caplog.at_level(logging.WARNING, logger="apcore_a2a.server.factory"):
        _create(registry, executor, sys_modules=True)
    assert "system.control" not in caplog.text


def test_an_executor_without_the_accessor_is_tolerated(registry_with_a_user_module, caplog):
    """srs FR-AGC-007 criterion 5. The reaction is a diagnostic, not a dependency:
    a backend that predates `governance_state()` must still start."""

    class _NoAccessor:
        def use(self, _middleware):  # the factory's own capability probe
            return None

    registry = registry_with_a_user_module
    with caplog.at_level(logging.WARNING, logger="apcore_a2a.server.factory"):
        _create(registry, _NoAccessor())
    assert "system.control" not in caplog.text


def test_warns_when_the_control_surface_is_unprotected(registry_with_a_user_module, caplog):
    """srs FR-AGC-007 criterion 2.

    Reached the way a real deployment reaches it: the operator builds their own
    apcore stack with `sys_modules.events` enabled — which is what registers the
    three `system.control.*` write modules — and hands the Executor to this
    package. apcore's approval gate warns once and continues when no
    `ApprovalHandler` is configured, so those modules stay callable even though
    FR-AGC-003 criterion 12 keeps them off the public card. Visibility and
    invocability are separate questions, and this warning is what stops the card
    rule being mistaken for a fix to the second.
    """
    from apcore import register_sys_modules
    from apcore.config import Config

    registry = registry_with_a_user_module
    executor = Executor(registry)
    register_sys_modules(
        registry,
        executor,
        Config(data={"sys_modules": {"enabled": True, "events": {"enabled": True}}}),
    )
    assert executor.governance_state().unprotected_control_surface is True, "precondition"

    with caplog.at_level(logging.WARNING, logger="apcore_a2a.server.factory"):
        _, card = _create(registry, executor)

    assert "system.control" in caplog.text
    assert "remain callable" in caplog.text
    # The warning is a diagnostic and changes nothing: the card rule already
    # withheld the whole namespace, control modules included.
    assert [skill.id for skill in card.skills] == ["math.add"]
