"""Tests for AgentCardBuilder."""

from unittest.mock import MagicMock

import pytest
from a2a.types import AgentCapabilities, AgentCard

from apcore_a2a.adapters.agent_card import AgentCardBuilder
from apcore_a2a.adapters.skill_mapper import SkillMapper


@pytest.fixture
def builder():
    return AgentCardBuilder(SkillMapper())


@pytest.fixture
def capabilities():
    # a2a-sdk 1.0: no state_transition_history field
    return AgentCapabilities(streaming=False, push_notifications=False)


@pytest.fixture
def mock_registry(simple_descriptor):
    reg = MagicMock()
    reg.list.return_value = ["image.resize"]
    reg.get_definition.return_value = simple_descriptor
    return reg


def test_build_returns_agent_card_model(builder, mock_registry, capabilities):
    card = builder.build(
        mock_registry,
        name="Test Agent",
        description="desc",
        version="1.0.0",
        url="http://localhost:8000",
        capabilities=capabilities,
    )
    assert isinstance(card, AgentCard)


def test_build_has_required_fields(builder, mock_registry, capabilities):
    card = builder.build(
        mock_registry,
        name="Test Agent",
        description="desc",
        version="1.0.0",
        url="http://localhost:8000",
        capabilities=capabilities,
    )
    assert card.name == "Test Agent"
    assert card.description == "desc"
    assert card.version == "1.0.0"
    # In a2a-sdk 1.0, url is in supported_interfaces
    assert any(iface.url == "http://localhost:8000" for iface in card.supported_interfaces)
    assert card.skills is not None
    assert card.capabilities is not None


def test_build_skills_populated(builder, mock_registry, capabilities):
    card = builder.build(
        mock_registry,
        name="A",
        description="B",
        version="1",
        url="http://x",
        capabilities=capabilities,
    )
    assert len(card.skills) == 1
    assert card.skills[0].id == "image.resize"


def test_build_skips_whitespace_only_description(builder, simple_descriptor, capabilities):
    """A-D-010: a module whose description is whitespace-only ("   ") is
    treated as having no meaningful description and skipped from the card,
    matching Rust's trim behavior."""
    simple_descriptor.description = "   "
    reg = MagicMock()
    reg.list.return_value = ["image.resize"]
    reg.get_definition.return_value = simple_descriptor

    card = builder.build(
        reg,
        name="A",
        description="B",
        version="1",
        url="http://x",
        capabilities=capabilities,
    )
    assert len(card.skills) == 0


def test_build_security_schemes_added(builder, mock_registry, capabilities):
    schemes = {"bearerAuth": {"type": "http", "scheme": "bearer"}}
    card = builder.build(
        mock_registry,
        name="A",
        description="B",
        version="1",
        url="http://x",
        capabilities=capabilities,
        security_schemes=schemes,
    )
    # In a2a-sdk 1.0, security_schemes is a proto map — non-empty when set
    assert "bearerAuth" in card.security_schemes


def test_build_no_security_schemes_when_none(builder, mock_registry, capabilities):
    card = builder.build(
        mock_registry,
        name="A",
        description="B",
        version="1",
        url="http://x",
        capabilities=capabilities,
    )
    # In a2a-sdk 1.0, security_schemes is a proto map — empty when no schemes
    assert len(card.security_schemes) == 0


def test_build_default_io_modes(builder, mock_registry, capabilities):
    card = builder.build(
        mock_registry,
        name="A",
        description="B",
        version="1",
        url="http://x",
        capabilities=capabilities,
    )
    assert "text/plain" in card.default_input_modes
    assert "application/json" in card.default_input_modes


def test_invalidate_cache(builder, mock_registry, capabilities):
    base = builder.build(
        mock_registry,
        name="A",
        description="B",
        version="1",
        url="http://x",
        capabilities=capabilities,
    )
    builder._cached_extended_card = builder.build_extended(base_card=base)
    builder.invalidate_cache()
    assert builder._cached_card is None
    assert builder._cached_extended_card is None


def test_build_extended_returns_agent_card(builder, mock_registry, capabilities):
    base = builder.build(
        mock_registry,
        name="A",
        description="B",
        version="1",
        url="http://x",
        capabilities=capabilities,
    )
    extended = builder.build_extended(base_card=base)
    assert isinstance(extended, AgentCard)
