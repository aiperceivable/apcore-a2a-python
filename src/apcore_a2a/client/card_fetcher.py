"""AgentCardFetcher: TTL-cached Agent Card discovery."""
from __future__ import annotations
import time
import httpx
from apcore_a2a.client.exceptions import A2ADiscoveryError


class AgentCardFetcher:
    def __init__(self, http: httpx.AsyncClient, base_url: str, *, ttl: float = 300.0) -> None:
        self._http = http
        self._url = f"{base_url}/.well-known/agent.json"
        self._ttl = ttl
        self._cached: dict | None = None
        self._cached_at: float = 0.0

    async def fetch(self) -> dict:
        """Fetch Agent Card, returning cached version if within TTL.

        Steps:
        1. now = time.monotonic()
        2. If cached is not None and (now - cached_at) < ttl -> return cached.
        3. GET self._url.
        4. If HTTP status != 200 -> raise A2ADiscoveryError with message.
        5. Parse JSON -> raise A2ADiscoveryError on parse error.
        6. Store in self._cached, update self._cached_at = now.
        7. Return cached dict.

        Raises:
            A2ADiscoveryError: HTTP error or invalid JSON in response.
        """
        now = time.monotonic()
        if self._cached is not None and (now - self._cached_at) < self._ttl:
            return self._cached
        response = await self._http.get(self._url)
        if response.status_code != 200:
            raise A2ADiscoveryError(
                f"Agent Card fetch failed: HTTP {response.status_code} from {self._url}"
            )
        try:
            card = response.json()
        except Exception as e:
            raise A2ADiscoveryError(f"Invalid JSON in Agent Card from {self._url}: {e}") from e
        self._cached = card
        self._cached_at = now
        return card
