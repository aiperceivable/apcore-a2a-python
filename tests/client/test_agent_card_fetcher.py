"""Tests for AgentCardFetcher."""
import time
import pytest
from unittest.mock import AsyncMock, MagicMock
from apcore_a2a.client.card_fetcher import AgentCardFetcher
from apcore_a2a.client.exceptions import A2ADiscoveryError

AGENT_CARD = {"name": "Test Agent", "version": "1.0.0", "skills": []}

@pytest.fixture
def mock_http():
    http = MagicMock()
    return http

async def test_fetch_success(mock_http):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = AGENT_CARD
    mock_http.get = AsyncMock(return_value=response)

    fetcher = AgentCardFetcher(mock_http, "http://localhost:8000", ttl=300.0)
    result = await fetcher.fetch()
    assert result == AGENT_CARD

async def test_fetch_http_error_raises(mock_http):
    response = MagicMock()
    response.status_code = 404
    mock_http.get = AsyncMock(return_value=response)

    fetcher = AgentCardFetcher(mock_http, "http://localhost:8000")
    with pytest.raises(A2ADiscoveryError, match="404"):
        await fetcher.fetch()

async def test_fetch_invalid_json_raises(mock_http):
    response = MagicMock()
    response.status_code = 200
    response.json.side_effect = ValueError("invalid json")
    mock_http.get = AsyncMock(return_value=response)

    fetcher = AgentCardFetcher(mock_http, "http://localhost:8000")
    with pytest.raises(A2ADiscoveryError):
        await fetcher.fetch()

async def test_fetch_uses_cache_within_ttl(mock_http):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = AGENT_CARD
    mock_http.get = AsyncMock(return_value=response)

    fetcher = AgentCardFetcher(mock_http, "http://localhost:8000", ttl=300.0)
    result1 = await fetcher.fetch()
    result2 = await fetcher.fetch()
    # Should only call HTTP once
    assert mock_http.get.call_count == 1
    assert result1 == result2

async def test_fetch_refreshes_after_ttl(mock_http):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = AGENT_CARD
    mock_http.get = AsyncMock(return_value=response)

    # TTL of 0 means always expired
    fetcher = AgentCardFetcher(mock_http, "http://localhost:8000", ttl=0.0)
    await fetcher.fetch()
    await fetcher.fetch()
    assert mock_http.get.call_count == 2

async def test_correct_url_used(mock_http):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = AGENT_CARD
    mock_http.get = AsyncMock(return_value=response)

    fetcher = AgentCardFetcher(mock_http, "http://agent.example.com", ttl=300.0)
    await fetcher.fetch()
    mock_http.get.assert_called_once_with("http://agent.example.com/.well-known/agent.json")
