"""AgentCardBuilder: builds a2a.types.AgentCard from Registry metadata."""

from __future__ import annotations

import logging
from typing import Any

from a2a.types import AgentCapabilities, AgentCard

from apcore_a2a.adapters.skill_mapper import SkillMapper

logger = logging.getLogger(__name__)


class AgentCardBuilder:
    """Builds a2a.types.AgentCard Pydantic models from Registry metadata.

    Caches the last-built card; call invalidate_cache() when registry changes.
    """

    def __init__(self, skill_mapper: SkillMapper) -> None:
        self._skill_mapper = skill_mapper
        self._cached_card: AgentCard | None = None
        self._cached_extended_card: AgentCard | None = None

    def build(
        self,
        registry: Any,
        *,
        name: str,
        description: str,
        version: str,
        url: str,
        capabilities: AgentCapabilities,
        security_schemes: Any | None = None,
    ) -> AgentCard:
        """Build and cache an a2a.types.AgentCard.

        Args:
            registry: Duck-typed registry with list() and get_definition() methods.
            name: Agent display name.
            description: Agent description.
            version: Agent version string.
            url: Agent base URL.
            capabilities: a2a.types.AgentCapabilities instance.
            security_schemes: Optional security scheme value (passed to AgentCard).

        Returns:
            a2a.types.AgentCard Pydantic model.
        """
        skills = self._build_skills(registry)

        card = AgentCard(
            name=name,
            description=description,
            version=version,
            url=url,
            skills=skills,
            capabilities=capabilities,
            default_input_modes=["text/plain", "application/json"],
            default_output_modes=["text/plain", "application/json"],
            security_schemes=security_schemes,
            supports_authenticated_extended_card=security_schemes is not None,
        )

        self._cached_card = card
        return card

    def get_cached_or_build(
        self,
        registry: Any,
        *,
        name: str,
        description: str,
        version: str,
        url: str,
        capabilities: AgentCapabilities,
        security_schemes: Any | None = None,
    ) -> AgentCard:
        """Return cached card if available, otherwise build a new one."""
        if self._cached_card is not None:
            return self._cached_card
        return self.build(
            registry,
            name=name,
            description=description,
            version=version,
            url=url,
            capabilities=capabilities,
            security_schemes=security_schemes,
        )

    def build_extended(
        self,
        *,
        base_card: AgentCard,
    ) -> AgentCard:
        """Build an extended AgentCard for authenticated users.

        Returns a deep copy of the base card. Override in a subclass to include
        additional skill metadata available only to authenticated callers.
        """
        return base_card.model_copy(deep=True)

    def invalidate_cache(self) -> None:
        """Invalidate cached cards (call on registry module add/remove)."""
        self._cached_card = None
        self._cached_extended_card = None

    def _build_skills(self, registry: Any) -> list:
        """Build the skills list from registry."""
        skills = []
        for module_id in registry.list():
            descriptor = registry.get_definition(module_id)
            if descriptor is None:
                continue

            description = getattr(descriptor, "description", None)
            if not description:
                logger.warning("Skipping module %s: missing description", module_id)
                continue

            skill = self._skill_mapper.to_skill(descriptor)
            if skill is not None:
                skills.append(skill)

        return skills
