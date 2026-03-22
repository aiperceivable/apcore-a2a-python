<div align="center">
  <img src="https://raw.githubusercontent.com/aiperceivable/apcore-a2a/main/apcore-a2a-logo.svg" alt="apcore-a2a logo" width="200"/>
</div>

# apcore-a2a (Python)

[![PyPI](https://img.shields.io/pypi/v/apcore-a2a)](https://pypi.org/project/apcore-a2a/)
[![Python](https://img.shields.io/pypi/pyversions/apcore-a2a)](https://pypi.org/project/apcore-a2a/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Coverage](https://img.shields.io/badge/coverage-90%25-brightgreen)](https://github.com/aiperceivable/apcore-a2a-python)

## What is apcore-a2a?

**apcore-a2a** is the [A2A (Agent-to-Agent)](https://google.github.io/A2A/) protocol adapter for the [apcore](https://github.com/aiperceivable/apcore-python) ecosystem.

It solves a common problem: **you've built AI capabilities with apcore modules, but you need them to talk to other AI agents over a standard protocol.** apcore-a2a bridges that gap — it reads your existing module metadata (schemas, descriptions, examples) and automatically exposes them as a standards-compliant A2A server. No hand-written Agent Cards, no JSON-RPC boilerplate, no manual task lifecycle management.

**In short:** `apcore modules` + `apcore-a2a` = a fully functional A2A agent, ready to be discovered and invoked by any A2A-compatible client.

> **Also available in TypeScript:** [`apcore-a2a` (npm)](https://github.com/aiperceivable/apcore-a2a-typescript)

## Features

- **One-call server** — launch a compliant A2A server with `serve(registry)`
- **Automatic Agent Card** — `/.well-known/agent.json` generated from module metadata
- **Skill mapping** — apcore modules become A2A Skills with names, descriptions, tags, and examples
- **Full task lifecycle** — submitted, working, completed, failed, canceled, input-required
- **SSE streaming** — `message/stream` with real-time status and artifact updates
- **Push notifications** — optional webhook delivery of task state changes
- **JWT authentication** — tokens bridged to apcore's Identity context
- **A2A Explorer UI** — browser UI for discovering and testing skills
- **Built-in client** — `A2AClient` for calling remote A2A agents
- **Pluggable storage** — swap in Redis or PostgreSQL via the `TaskStore` protocol
- **Observability** — `/health`, `/metrics` endpoints, structured logging
- **Dynamic registration** — add/remove modules at runtime without restart

## Requirements

- Python >= 3.11
- `apcore` >= 0.9.0

---

## For Users: Getting Started

### Installation

```bash
pip install apcore-a2a
```

### Expose your modules as an A2A Agent

If you already have apcore modules, a few lines turn them into a discoverable agent:

```python
from apcore import Executor, Registry
from apcore_a2a import serve

registry = Registry(extensions_dir="./extensions")
registry.discover()

serve(Executor(registry))  # Starts on http://0.0.0.0:8000
```

Your agent is now live at `http://localhost:8000/.well-known/agent.json`.

### Try the Examples

Run all 5 example modules (3 class-based + 2 binding YAML) with the Explorer UI:

```bash
PYTHONPATH=./examples/binding_demo python examples/run.py
```

Open http://127.0.0.1:8000/explorer/ to browse skills, send messages, and stream responses.

See [`examples/README.md`](examples/README.md) for more options (CLI, binding-only, JWT auth).

### Call a remote A2A Agent

Use the built-in client to discover and invoke any A2A-compliant agent:

```python
import asyncio
from apcore_a2a import A2AClient

async def main():
    async with A2AClient("http://remote-agent:8000") as client:
        # Discover what the agent can do
        card = await client.discover()
        print(f"Agent: {card['name']}, Skills: {len(card['skills'])}")

        # Send a message
        task = await client.send_message(
            {"role": "user", "parts": [{"kind": "text", "text": "Hello!"}]},
            skill_id="my.skill",
        )
        print(f"Result: {task['status']['state']}")

        # Or stream the response
        async for event in client.stream_message(...):
            print(event)

asyncio.run(main())
```

### Add authentication

```python
from apcore_a2a import serve
from apcore_a2a.auth.jwt import JWTAuthenticator, ClaimMapping

auth = JWTAuthenticator(
    key="your-secret-key",
    algorithms=["HS256"],
    issuer="https://auth.example.com",
    audience="my-agent",
    claim_mapping=ClaimMapping(
        id_claim="sub",
        type_claim="type",
        roles_claim="roles",
        attrs_claims=["org", "dept"],
    ),
    require_claims=["sub"],
)

serve(registry, auth=auth)
```

---

## For Developers: API Reference

### `serve()`

Blocking call — starts uvicorn and serves until SIGINT/SIGTERM.

```python
from apcore_a2a import serve

serve(
    registry_or_executor,   # apcore Registry or Executor
    *,
    host="0.0.0.0",
    port=8000,
    name=None,              # Agent name (fallback: registry config)
    description=None,       # Agent description
    version=None,           # Agent version
    url=None,               # Public URL (default: f"http://{host}:{port}")
    auth=None,              # Authenticator instance
    task_store=None,        # TaskStore instance (default: InMemoryTaskStore)
    cors_origins=None,      # List of allowed CORS origins
    push_notifications=False,
    explorer=False,         # Enable A2A Explorer UI
    explorer_prefix="/explorer",
    cancel_on_disconnect=True,
    shutdown_timeout=30,
    execution_timeout=300,
    log_level=None,
    metrics=False,          # Enable /metrics endpoint
)
```

### `async_serve()`

Returns the ASGI app without starting a server — use for embedding in larger applications.

```python
from apcore_a2a import async_serve

app = await async_serve(registry_or_executor, **kwargs)
# app is a Starlette ASGI application
```

### `TaskStore`

Default in-memory task store. Implement the `TaskStore` protocol for persistent backends (Redis, PostgreSQL, etc.).

```python
from apcore_a2a.storage.memory import InMemoryTaskStore

store = InMemoryTaskStore()
serve(registry, task_store=store)
```

### Architecture

apcore-a2a acts as a thin protocol layer on top of apcore. The mapping is straightforward:

| A2A Concept    | apcore Mapping                            |
| -------------- | ----------------------------------------- |
| **Agent Card** | Derived from Registry configuration       |
| **Skill**      | Maps 1:1 to an apcore Module              |
| **Task**       | Managed execution of `Executor.call_async()` |
| **Streaming**  | Wrapped `Executor.stream()` via SSE       |
| **Security**   | Bridged to apcore's `Identity` context    |

### Contributing

```bash
git clone https://github.com/aiperceivable/apcore-a2a-python.git
cd apcore-a2a-python
pip install -e ".[dev]"
pytest
```

## Documentation

- [Product Requirements (PRD)](https://github.com/aiperceivable/apcore-a2a/blob/main/docs/apcore-a2a/prd.md)
- [Technical Design](https://github.com/aiperceivable/apcore-a2a/blob/main/docs/apcore-a2a/tech-design.md)
- [Software Requirements (SRS)](https://github.com/aiperceivable/apcore-a2a/blob/main/docs/apcore-a2a/srs.md)

## License

Apache 2.0 — see [LICENSE](LICENSE).
