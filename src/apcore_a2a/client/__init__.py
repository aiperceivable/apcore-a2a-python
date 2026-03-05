"""Client: A2AClient, AgentCardFetcher, client exceptions."""

from apcore_a2a.client.card_fetcher import AgentCardFetcher
from apcore_a2a.client.client import A2AClient
from apcore_a2a.client.exceptions import (
    A2AClientError,
    A2AConnectionError,
    A2ADiscoveryError,
    A2AServerError,
    TaskNotCancelableError,
    TaskNotFoundError,
)

__all__ = [
    "A2AClient",
    "AgentCardFetcher",
    "A2AClientError",
    "A2AConnectionError",
    "A2ADiscoveryError",
    "A2AServerError",
    "TaskNotFoundError",
    "TaskNotCancelableError",
]
