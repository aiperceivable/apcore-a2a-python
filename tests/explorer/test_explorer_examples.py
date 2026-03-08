"""Integration tests: Examples + Explorer with real apcore modules.

Verifies that the examples directory modules load correctly and that
the Explorer UI + A2A endpoints work end-to-end against them.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from starlette.testclient import TestClient

# Ensure binding_demo is on sys.path so binding YAML can resolve `myapp:*`
_BINDING_DEMO_DIR = str(Path(__file__).parents[2] / "examples" / "binding_demo")
if _BINDING_DEMO_DIR not in sys.path:
    sys.path.insert(0, _BINDING_DEMO_DIR)

EXAMPLES_DIR = Path(__file__).parents[2] / "examples"
EXTENSIONS_DIR = EXAMPLES_DIR / "extensions"
BINDING_DIR = EXAMPLES_DIR / "binding_demo" / "extensions"


# ── Helpers ──────────────────────────────────────────────────────────────────


def _jsonrpc(method: str, params: dict, rpc_id: int = 1) -> dict:
    """Build a JSON-RPC 2.0 request body."""
    return {"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params}


def _make_message(skill_id: str | None, text: str) -> dict:
    """Build a valid A2A Message dict with all required fields."""
    msg: dict = {
        "role": "user",
        "parts": [{"kind": "text", "text": text}],
        "messageId": str(uuid4()),
        "contextId": str(uuid4()),
    }
    if skill_id is not None:
        msg["metadata"] = {"skillId": skill_id}
    return msg


def _send(client: TestClient, skill_id: str, inputs: dict) -> dict:
    """Send a message/send with JSON-encoded inputs and return the response."""
    body = _jsonrpc(
        "message/send",
        {"message": _make_message(skill_id, json.dumps(inputs))},
    )
    resp = client.post("/", json=body)
    assert resp.status_code == 200
    return resp.json()


def _extract_output(result: dict) -> dict:
    """Extract the output data from a completed task result.

    The artifact part may be either:
    - {"kind": "data", "data": {...}}  — structured output
    - {"kind": "text", "text": "..."}  — JSON-encoded text output
    """
    artifact = result["result"]["artifacts"][0]
    part = artifact["parts"][0]
    if part.get("kind") == "data":
        return part["data"]
    return json.loads(part["text"])


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def app():
    """Build a full A2A Starlette app with all 5 example modules + explorer."""
    from apcore import BindingLoader, Executor, Registry

    from apcore_a2a._serve import async_serve

    registry = Registry(extensions_dir=str(EXTENSIONS_DIR))
    registry.discover()
    loader = BindingLoader()
    loader.load_binding_dir(str(BINDING_DIR), registry)

    executor = Executor(registry)
    return asyncio.run(async_serve(executor, explorer=True))


@pytest.fixture(scope="module")
def client(app):
    """Starlette TestClient for the full app."""
    return TestClient(app)


# ── TC-EX-01: Explorer index page loads ──────────────────────────────────────


class TestExplorerIndex:
    def test_returns_200(self, client):
        resp = client.get("/explorer/")
        assert resp.status_code == 200

    def test_content_type_html(self, client):
        resp = client.get("/explorer/")
        assert "text/html" in resp.headers["content-type"]

    def test_contains_title(self, client):
        assert "APCore A2A Agent Explorer" in client.get("/explorer/").text

    def test_contains_ui_sections(self, client):
        html = client.get("/explorer/").text
        assert "Agent Card" in html
        assert "Skills" in html
        assert "Message Composer" in html
        assert "SSE Stream Viewer" in html
        assert "Task Viewer" in html

    def test_contains_send_button(self, client):
        assert "message/send" in client.get("/explorer/").text

    def test_contains_stream_button(self, client):
        assert "message/stream" in client.get("/explorer/").text

    def test_contains_task_operations(self, client):
        html = client.get("/explorer/").text
        assert "tasks/get" in html
        assert "tasks/cancel" in html


# ── TC-EX-02: Explorer agent-card endpoint ───────────────────────────────────


class TestExplorerAgentCard:
    def test_returns_200_json(self, client):
        resp = client.get("/explorer/agent-card")
        assert resp.status_code == 200
        assert "application/json" in resp.headers["content-type"]

    def test_card_has_name(self, client):
        data = client.get("/explorer/agent-card").json()
        assert isinstance(data["name"], str)
        assert len(data["name"]) > 0

    def test_card_has_version(self, client):
        assert "version" in client.get("/explorer/agent-card").json()

    def test_card_has_url(self, client):
        assert client.get("/explorer/agent-card").json()["url"].startswith("http")

    def test_card_has_capabilities(self, client):
        caps = client.get("/explorer/agent-card").json()["capabilities"]
        assert caps.get("streaming") is True

    def test_card_has_default_modes(self, client):
        data = client.get("/explorer/agent-card").json()
        assert "text/plain" in data["defaultInputModes"]
        assert "application/json" in data["defaultInputModes"]
        assert "text/plain" in data["defaultOutputModes"]


# ── TC-EX-03: All 5 example skills appear in agent card ─────────────────────


class TestExplorerSkills:
    EXPECTED_SKILL_IDS = {
        "convert_temperature",
        "greeting",
        "math_calc",
        "text_echo",
        "word_count",
    }

    def test_skill_count(self, client):
        assert len(client.get("/explorer/agent-card").json()["skills"]) == 5

    def test_all_skill_ids_present(self, client):
        skill_ids = {s["id"] for s in client.get("/explorer/agent-card").json()["skills"]}
        assert skill_ids == self.EXPECTED_SKILL_IDS

    def test_each_skill_has_name(self, client):
        for s in client.get("/explorer/agent-card").json()["skills"]:
            assert len(s["name"]) > 0, f"Skill {s['id']} missing name"

    def test_each_skill_has_description(self, client):
        for s in client.get("/explorer/agent-card").json()["skills"]:
            assert len(s["description"]) > 0, f"Skill {s['id']} missing description"

    def test_each_skill_has_tags(self, client):
        for s in client.get("/explorer/agent-card").json()["skills"]:
            assert len(s["tags"]) > 0, f"Skill {s['id']} missing tags"

    def test_skill_input_output_modes(self, client):
        for s in client.get("/explorer/agent-card").json()["skills"]:
            assert "inputModes" in s, f"Skill {s['id']} missing inputModes"
            assert "outputModes" in s, f"Skill {s['id']} missing outputModes"


# ── TC-EX-04: Well-known agent card endpoints ────────────────────────────────


class TestWellKnownAgentCard:
    def test_well_known_agent_json(self, client):
        resp = client.get("/.well-known/agent.json")
        assert resp.status_code == 200
        data = resp.json()
        assert "name" in data
        assert "skills" in data

    def test_well_known_agent_card_json(self, client):
        resp = client.get("/.well-known/agent-card.json")
        assert resp.status_code == 200
        assert "name" in resp.json()

    def test_well_known_matches_explorer(self, client):
        explorer_card = client.get("/explorer/agent-card").json()
        wellknown_card = client.get("/.well-known/agent.json").json()
        assert explorer_card["name"] == wellknown_card["name"]
        assert len(explorer_card["skills"]) == len(wellknown_card["skills"])


# ── TC-EX-05: message/send with text_echo skill ─────────────────────────────


class TestMessageSendTextEcho:
    def test_send_returns_completed(self, client):
        result = _send(client, "text_echo", {"text": "Hello world"})
        assert result["result"]["status"]["state"] == "completed"

    def test_send_has_artifact(self, client):
        task = _send(client, "text_echo", {"text": "Hello world"})["result"]
        assert len(task["artifacts"]) > 0

    def test_echo_output_correct(self, client):
        result = _send(client, "text_echo", {"text": "Hello world"})
        output = _extract_output(result)
        assert output["echoed"] == "Hello world"
        assert output["length"] == 11

    def test_echo_uppercase(self, client):
        result = _send(client, "text_echo", {"text": "hello", "uppercase": True})
        output = _extract_output(result)
        assert output["echoed"] == "HELLO"


# ── TC-EX-06: message/send with math_calc skill ─────────────────────────────


class TestMessageSendMathCalc:
    def test_add(self, client):
        output = _extract_output(_send(client, "math_calc", {"a": 3, "b": 5, "op": "add"}))
        assert output["result"] == 8.0
        assert "3" in output["expression"] and "5" in output["expression"]

    def test_multiply(self, client):
        output = _extract_output(_send(client, "math_calc", {"a": 4, "b": 7, "op": "mul"}))
        assert output["result"] == 28.0

    def test_divide(self, client):
        output = _extract_output(_send(client, "math_calc", {"a": 10, "b": 4, "op": "div"}))
        assert output["result"] == 2.5


# ── TC-EX-07: message/send with greeting skill ──────────────────────────────


class TestMessageSendGreeting:
    def test_friendly_greeting(self, client):
        output = _extract_output(_send(client, "greeting", {"name": "Alice", "style": "friendly"}))
        assert "Alice" in output["message"]
        assert "timestamp" in output

    def test_pirate_greeting(self, client):
        output = _extract_output(_send(client, "greeting", {"name": "Bob", "style": "pirate"}))
        assert "Bob" in output["message"]
        assert "Ahoy" in output["message"]


# ── TC-EX-08: message/send with convert_temperature (binding) ────────────────


class TestMessageSendConvertTemperature:
    def test_celsius_to_fahrenheit(self, client):
        output = _extract_output(
            _send(
                client,
                "convert_temperature",
                {"value": 100, "from_unit": "celsius", "to_unit": "fahrenheit"},
            )
        )
        assert output["result"] == 212.0

    def test_fahrenheit_to_celsius(self, client):
        output = _extract_output(
            _send(
                client,
                "convert_temperature",
                {"value": 32, "from_unit": "fahrenheit", "to_unit": "celsius"},
            )
        )
        assert output["result"] == 0.0


# ── TC-EX-09: message/send with word_count (binding) ────────────────────────


class TestMessageSendWordCount:
    def test_basic_count(self, client):
        output = _extract_output(_send(client, "word_count", {"text": "hello world foo bar"}))
        assert output["words"] == 4
        assert output["characters"] == 19


# ── TC-EX-10: message/send error cases ──────────────────────────────────────


class TestMessageSendErrors:
    def test_unknown_skill_fails(self, client):
        result = _send(client, "nonexistent_skill", {"text": "test"})
        assert result["result"]["status"]["state"] == "failed"

    def test_missing_skill_id_fails(self, client):
        body = _jsonrpc("message/send", {"message": _make_message(None, "hello")})
        resp = client.post("/", json=body)
        assert resp.json()["result"]["status"]["state"] == "failed"


# ── TC-EX-11: tasks/get retrieves a completed task ──────────────────────────


class TestTasksGet:
    def test_get_completed_task(self, client):
        send_result = _send(client, "text_echo", {"text": "test task get"})
        task_id = send_result["result"]["id"]

        body = _jsonrpc("tasks/get", {"id": task_id})
        resp = client.post("/", json=body)
        assert resp.status_code == 200
        task = resp.json()["result"]
        assert task["id"] == task_id
        assert task["status"]["state"] == "completed"

    def test_get_nonexistent_task(self, client):
        body = _jsonrpc("tasks/get", {"id": "nonexistent-task-id-12345"})
        resp = client.post("/", json=body)
        assert "error" in resp.json()


# ── TC-EX-12: message/stream returns SSE events ─────────────────────────────


class TestMessageStream:
    def test_stream_returns_sse(self, client):
        msg = _make_message("text_echo", json.dumps({"text": "stream test"}))
        body = _jsonrpc("message/stream", {"message": msg})
        resp = client.post("/", json=body, headers={"Accept": "text/event-stream"})
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

    def test_stream_contains_completed_event(self, client):
        msg = _make_message("text_echo", json.dumps({"text": "stream test 2"}))
        body = _jsonrpc("message/stream", {"message": msg})
        resp = client.post("/", json=body, headers={"Accept": "text/event-stream"})
        assert "completed" in resp.text


# ── TC-EX-13: health endpoint works alongside explorer ───────────────────────


class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        assert client.get("/health").status_code == 200

    def test_health_body(self, client):
        data = client.get("/health").json()
        assert data["status"] == "healthy"
        assert data["module_count"] == 5


# ── TC-EX-14: Explorer with custom prefix ───────────────────────────────────


class TestExplorerCustomPrefix:
    @pytest.fixture()
    def custom_app(self):
        from apcore import Executor, Registry

        from apcore_a2a._serve import async_serve

        registry = Registry(extensions_dir=str(EXTENSIONS_DIR))
        registry.discover()
        executor = Executor(registry)
        return asyncio.run(async_serve(executor, explorer=True, explorer_prefix="/dev"))

    def test_custom_prefix_index(self, custom_app):
        c = TestClient(custom_app)
        resp = c.get("/dev/")
        assert resp.status_code == 200
        assert "APCore A2A Agent Explorer" in resp.text

    def test_custom_prefix_agent_card(self, custom_app):
        c = TestClient(custom_app)
        resp = c.get("/dev/agent-card")
        assert resp.status_code == 200
        assert "skills" in resp.json()

    def test_default_prefix_404(self, custom_app):
        assert TestClient(custom_app).get("/explorer/").status_code == 404


# ── TC-EX-15: Explorer disabled by default ───────────────────────────────────


class TestExplorerDisabledByDefault:
    @pytest.fixture()
    def no_explorer_app(self):
        from apcore import Executor, Registry

        from apcore_a2a._serve import async_serve

        registry = Registry(extensions_dir=str(EXTENSIONS_DIR))
        registry.discover()
        executor = Executor(registry)
        return asyncio.run(async_serve(executor, explorer=False))

    def test_explorer_404_when_disabled(self, no_explorer_app):
        assert TestClient(no_explorer_app).get("/explorer/").status_code == 404

    def test_agent_card_still_works(self, no_explorer_app):
        assert TestClient(no_explorer_app).get("/.well-known/agent.json").status_code == 200


# ── TC-EX-16: Agent card serialization with Pydantic model ──────────────────


class TestAgentCardSerialization:
    def test_agent_card_is_valid_json(self, client):
        data = client.get("/explorer/agent-card").json()
        # Re-serialize to verify it's clean JSON (no Pydantic objects leaked)
        json.dumps(data)

    def test_agent_card_skills_are_plain_dicts(self, client):
        for skill in client.get("/explorer/agent-card").json()["skills"]:
            assert isinstance(skill, dict)
            assert isinstance(skill["id"], str)
            assert isinstance(skill["name"], str)


# ── TC-EX-17: Explorer HTML is self-contained ────────────────────────────────


class TestExplorerHtmlSelfContained:
    def test_no_external_scripts(self, client):
        html = client.get("/explorer/").text
        assert "cdn.jsdelivr.net" not in html
        assert "unpkg.com" not in html
        assert "cdnjs.cloudflare.com" not in html

    def test_has_inline_css(self, client):
        assert "<style>" in client.get("/explorer/").text

    def test_has_inline_js(self, client):
        assert "<script>" in client.get("/explorer/").text

    def test_js_fetches_agent_card(self, client):
        assert "/agent-card" in client.get("/explorer/").text

    def test_js_has_jsonrpc_methods(self, client):
        html = client.get("/explorer/").text
        assert "message/send" in html
        assert "message/stream" in html
        assert "tasks/get" in html
        assert "tasks/cancel" in html
