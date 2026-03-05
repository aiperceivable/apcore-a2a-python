# apcore-a2a

[![PyPI](https://img.shields.io/pypi/v/apcore-a2a)](https://pypi.org/project/apcore-a2a/)
[![Python](https://img.shields.io/pypi/pyversions/apcore-a2a)](https://pypi.org/project/apcore-a2a/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Coverage](https://img.shields.io/badge/coverage-90%25-brightgreen)](https://github.com/aipartnerup/apcore-a2a-python)

**apcore-a2a** automatically converts any apcore Module Registry into a fully functional [A2A (Agent-to-Agent) protocol](https://google.github.io/A2A/) server and client — zero boilerplate required.

## Installation

```bash
pip install apcore-a2a
```

## Quick Start

```python
from apcore import Registry
from apcore_a2a import serve

registry = Registry(extensions_dir="./extensions")
registry.discover()

serve(registry)  # Starts on http://0.0.0.0:8000
```

Agent Card is automatically served at `/.well-known/agent.json`. All registered modules appear as A2A Skills.

## Features

- **Automatic Agent Card generation** — modules mapped to Skills with names, descriptions, tags, and examples
- **JSON-RPC 2.0 transport** — `message/send` and `message/stream` endpoints
- **Full A2A task lifecycle** — submitted → working → completed/failed/canceled/input_required
- **SSE streaming** — `message/stream` with real-time `TaskStatusUpdateEvent` and `TaskArtifactUpdateEvent`
- **Push notifications** — optional webhook delivery of task state changes
- **JWT authentication** — `JWTAuthenticator` bridges tokens to apcore Identity context
- **A2A Explorer UI** — optional browser UI for discovering and testing skills
- **A2A client** — `A2AClient` for discovering and invoking remote A2A agents
- **Pluggable storage** — swap in Redis or PostgreSQL via the `TaskStore` protocol
- **Observability** — `/health`, `/metrics` endpoints, structured logging
- **Dynamic registration** — add/remove modules at runtime without restart

## API Reference

### `serve()`

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

Blocking call — starts uvicorn and serves until SIGINT/SIGTERM.

### `async_serve()`

```python
from apcore_a2a import async_serve

app = await async_serve(registry_or_executor, **kwargs)
# app is a Starlette ASGI application
```

Returns the ASGI app without starting a server — use for embedding in larger applications.

### `A2AClient`

```python
from apcore_a2a import A2AClient

async with A2AClient("http://agent.example.com") as client:
    card = await client.discover()
    task = await client.send_message(
        {"role": "user", "parts": [{"kind": "text", "text": "hello"}]},
        skill_id="my.skill",
    )
    async for event in client.stream_message(...):
        print(event)
```

### `JWTAuthenticator`

```python
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

### `AuthMiddleware`

```python
from apcore_a2a.auth.middleware import AuthMiddleware
```

Starlette middleware that calls `authenticator.authenticate(headers)` and sets the identity in the request scope. Automatically wired when `auth=` is passed to `serve()`.

### `InMemoryTaskStore`

```python
from apcore_a2a.storage.memory import InMemoryTaskStore

store = InMemoryTaskStore()
serve(registry, task_store=store)
```

Default in-memory task store. Implement the `TaskStore` protocol for persistent backends.

## License

Apache 2.0 — see [LICENSE](LICENSE).
