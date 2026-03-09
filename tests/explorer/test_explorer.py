"""Tests for Explorer UI feature (F-10)."""

from __future__ import annotations

from pathlib import Path

from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from apcore_a2a.explorer import create_explorer_mount

SAMPLE_CARD = {
    "name": "Test Agent",
    "description": "A test agent",
    "version": "1.0.0",
    "url": "http://localhost:8000",
    "capabilities": {"streaming": True},
    "skills": [
        {
            "id": "greet",
            "name": "Greet",
            "description": "Greet someone",
            "tags": ["greeting"],
            "inputModes": ["text"],
            "outputModes": ["text"],
        }
    ],
}


def make_test_app(agent_card, **kwargs):
    mount = create_explorer_mount(agent_card, router=None, **kwargs)
    app = Starlette(routes=[mount])
    return app


# ── T10-01: create_explorer_mount returns a Mount instance ──────────────────


def test_create_explorer_mount_returns_mount():
    result = create_explorer_mount(SAMPLE_CARD, router=None)
    assert isinstance(result, Mount), f"Expected Mount, got {type(result)}"


# ── T10-02: default prefix is /explorer ─────────────────────────────────────


def test_explorer_default_prefix():
    mount = create_explorer_mount(SAMPLE_CARD, router=None)
    assert mount.path == "/explorer"


# ── T10-03: custom prefix ───────────────────────────────────────────────────


def test_explorer_custom_prefix():
    mount = create_explorer_mount(SAMPLE_CARD, router=None, explorer_prefix="/dev")
    assert mount.path == "/dev"


# ── T10-04: GET / returns 200 ───────────────────────────────────────────────


def test_explorer_get_index_returns_200():
    client = TestClient(make_test_app(SAMPLE_CARD))
    resp = client.get("/explorer/")
    assert resp.status_code == 200


# ── T10-05: GET / Content-Type: text/html ───────────────────────────────────


def test_explorer_get_index_content_type():
    client = TestClient(make_test_app(SAMPLE_CARD))
    resp = client.get("/explorer/")
    assert "text/html" in resp.headers["content-type"]


# ── T10-06: GET /agent-card returns 200 JSON ────────────────────────────────


def test_explorer_get_agent_card_returns_json():
    client = TestClient(make_test_app(SAMPLE_CARD))
    resp = client.get("/explorer/agent-card")
    assert resp.status_code == 200
    assert "application/json" in resp.headers["content-type"]


# ── T10-07: /agent-card body equals the passed dict ─────────────────────────


def test_explorer_agent_card_content():
    client = TestClient(make_test_app(SAMPLE_CARD))
    resp = client.get("/explorer/agent-card")
    assert resp.json() == SAMPLE_CARD


# ── T10-08: no auth imports in explorer/__init__.py ─────────────────────────


def test_explorer_no_auth_imports():
    init_path = Path(__file__).parents[2] / "src" / "apcore_a2a" / "explorer" / "__init__.py"
    source = init_path.read_text()
    assert "from apcore_a2a.auth" not in source, "explorer/__init__.py must NOT import from apcore_a2a.auth"


# ── T10-09: no storage imports in explorer/__init__.py ──────────────────────


def test_explorer_no_storage_imports():
    init_path = Path(__file__).parents[2] / "src" / "apcore_a2a" / "explorer" / "__init__.py"
    source = init_path.read_text()
    assert "from apcore_a2a.storage" not in source, "explorer/__init__.py must NOT import from apcore_a2a.storage"


# ── T10-10: index.html has no external CDN URLs ──────────────────────────────


def test_index_html_no_cdn():
    html_path = Path(__file__).parents[2] / "src" / "apcore_a2a" / "explorer" / "index.html"
    assert html_path.exists(), "index.html must exist"
    content = html_path.read_text()
    forbidden = [
        "cdn.jsdelivr.net",
        "unpkg.com",
        "fonts.googleapis.com",
        "fonts.gstatic.com",
        "cdnjs.cloudflare.com",
        "ajax.googleapis.com",
    ]
    for url in forbidden:
        assert url not in content, f"index.html must not reference external CDN: {url}"


# ── T10-11: explorer HTML contains auth bar ──────────────────────────────────


def test_explorer_html_has_auth_bar():
    client = TestClient(make_test_app(SAMPLE_CARD))
    html = client.get("/explorer/").text
    assert "auth-token" in html, "Explorer HTML must contain auth-token input"
    assert 'type="password"' in html, "Auth token input must be type=password"
    assert "auth-status" in html, "Explorer HTML must contain auth status badge"


# ── T10-12: explorer HTML contains curl section ──────────────────────────────


def test_explorer_html_has_curl_section():
    client = TestClient(make_test_app(SAMPLE_CARD))
    html = client.get("/explorer/").text
    assert "curl-section" in html, "Explorer HTML must contain curl section"
    assert "curl-cmd" in html, "Explorer HTML must contain curl command element"
    assert "copy-btn" in html, "Explorer HTML must contain copy button"


# ── T10-13: explorer HTML has no inline onclick on example links ─────────────


def test_explorer_html_no_inline_onclick_examples():
    """Example links must use data attributes, not inline onclick handlers."""
    html_path = Path(__file__).parents[2] / "src" / "apcore_a2a" / "explorer" / "index.html"
    content = html_path.read_text()
    assert 'onclick="useExample' not in content, "example-link must not use inline onclick"
    assert "data-skill-id" in content, "example-link must use data-skill-id attribute"
    assert "data-example" in content, "example-link must use data-example attribute"
