"""Explorer: browser-based A2A agent UI."""

from __future__ import annotations

from pathlib import Path

from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Mount, Route


def create_explorer_mount(
    agent_card,
    router,
    *,
    explorer_prefix: str = "/explorer",
    authenticator=None,
    registry=None,
) -> Mount:
    """Create a Starlette Mount that serves the A2A Explorer UI.

    Routes:
        GET {explorer_prefix}/            — serves index.html
        GET {explorer_prefix}/agent-card  — serves agent_card as JSON
    """
    html_path = Path(__file__).parent / "index.html"

    async def serve_index(request):
        return HTMLResponse(html_path.read_text())

    async def serve_agent_card(request):
        # a2a-sdk 1.0: AgentCard is a protobuf message; convert to JSON-safe dict
        from google.protobuf.json_format import MessageToDict

        if hasattr(agent_card, "DESCRIPTOR"):
            data: dict = MessageToDict(agent_card, preserving_proto_field_name=False)
        elif hasattr(agent_card, "model_dump"):
            data = agent_card.model_dump(mode="json", exclude_none=True)
        else:
            data = dict(agent_card)
        # Attach input schemas for the explorer UI to generate sample inputs
        if registry is not None:
            schemas = {}
            for skill in data.get("skills", []):
                sid = skill.get("id")
                if sid:
                    desc = registry.get_definition(sid)
                    schema = getattr(desc, "input_schema", None) if desc else None
                    if isinstance(schema, dict):
                        schemas[sid] = schema
            if schemas:
                data["_inputSchemas"] = schemas
        return JSONResponse(data)

    return Mount(
        explorer_prefix,
        routes=[
            Route("/", endpoint=serve_index),
            Route("/agent-card", endpoint=serve_agent_card),
        ],
    )


__all__ = ["create_explorer_mount"]
