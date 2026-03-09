# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-03-08

### Added

#### Explorer UX improvements (`apcore_a2a.explorer`)
- **Auth token bar** — persistent token input (`type="password"`) below header with status indicator; automatically included in all requests and generated curl commands
- **Curl command generation** — collapsible curl block with Copy button after each Send/Stream request; properly escapes shell single quotes in URL, auth header, and body
- **Clickable skill examples** — example links in the sidebar that auto-fill the Message Composer on click; uses event delegation (data attributes) instead of inline handlers
- **Schema-based sample inputs** — explorer endpoint now includes `_inputSchemas` from registry; skills without examples auto-generate a sample JSON input from the schema (same clickable UX as explicit examples)
- **`messageId` in Message Composer** — requests now include the required `messageId` field (was causing `-32602 Field required` errors)

#### Examples (`examples/`)
- Unified launcher `examples/run.py` — starts all 5 example modules with Explorer UI
- 3 class-based modules: `text_echo`, `math_calc`, `greeting`
- 2 binding YAML modules: `convert_temperature`, `word_count` (zero-code integration via `myapp.py`)
- Binding-only launcher `examples/binding_demo/run.py`
- `examples/README.md` with quick start, Explorer UI guide, JWT auth, and cURL examples
- `ModuleExample` definitions for `text_echo`, `math_calc`, `greeting` — provides clickable examples in Explorer

#### Tests
- 54 integration tests (`tests/explorer/test_explorer_examples.py`) covering Explorer UI, agent card, all 5 skills end-to-end, streaming, task lifecycle, error cases, custom prefix, and disabled explorer
- 3 new Explorer unit tests: auth bar presence, curl section presence, no inline onclick on example links

### Fixed
- **Explorer agent card serialization** — `AgentCard` Pydantic model now properly serialized via `model_dump()` before passing to `JSONResponse` (was causing `TypeError: Object of type AgentCard is not JSON serializable`)
- **Explorer type hint** — `create_explorer_mount` parameter `agent_card` no longer incorrectly typed as `dict`
- **SSE stream parsing** — last event in stream was silently dropped when not followed by `\n\n`; remaining buffer is now flushed on stream end
- **Default agent name** — changed from `"apcore-agent"` to `"Apcore Agent"` to avoid confusion with a package/program name

### Changed
- Bumped `apcore` dependency from `>=0.7.0` to `>=0.9.0`

---

## [0.1.0] - 2026-03-06

Initial release — automatic A2A protocol adapter for apcore Module Registry.

### Added

#### Adapters (`apcore_a2a.adapters`)
- `SkillMapper` — converts apcore module definitions to `a2a.types.AgentSkill`
- `AgentCardBuilder` — builds `a2a.types.AgentCard` from registry metadata with caching and cache invalidation
- `PartConverter` — bidirectional conversion between A2A `Part`/`Artifact` and apcore formats
- `SchemaConverter` — converts apcore JSON schemas to A2A-compatible schemas
- `ErrorMapper` — maps apcore exceptions to A2A JSON-RPC error codes

#### Server (`apcore_a2a.server`)
- `A2AServerFactory` — wires all components into a Starlette ASGI app via `a2a-sdk`
- `ApCoreAgentExecutor` — implements `a2a.server.agent_execution.AgentExecutor`, bridges A2A requests to apcore executor
- Full A2A task lifecycle: submitted → working → completed / failed / canceled / input_required
- SSE streaming via `message/stream` with `TaskStatusUpdateEvent` and `TaskArtifactUpdateEvent`
- Push notification support with `InMemoryPushNotificationConfigStore`
- Dynamic module registration at runtime without restart
- CORS middleware support via `cors_origins` parameter

#### Storage (`apcore_a2a.storage`)
- Re-exports `a2a-sdk` `TaskStore` protocol and `InMemoryTaskStore`
- Pluggable storage interface for custom backends (Redis, PostgreSQL, etc.)

#### Auth (`apcore_a2a.auth`)
- `JWTAuthenticator` — validates JWT bearer tokens, maps claims to apcore `Identity`
- `ClaimMapping` — configurable mapping of JWT claims to identity fields (id, type, roles, attrs)
- `AuthMiddleware` — Starlette middleware with configurable exempt paths and prefixes
- `Authenticator` protocol for custom authentication backends
- Security scheme generation for AgentCard (`supports_authenticated_extended_card`)

#### Client (`apcore_a2a.client`)
- `A2AClient` — async client for discovering and invoking remote A2A agents
- `AgentCardFetcher` — fetches and caches agent cards from `/.well-known/agent.json`
- `send_message()`, `get_task()`, `cancel_task()` via JSON-RPC 2.0
- `stream_message()` — async iterator over SSE events with automatic `final` detection
- Typed exception hierarchy: `A2AClientError`, `A2AConnectionError`, `A2ADiscoveryError`, `TaskNotFoundError`, `TaskNotCancelableError`, `A2AServerError`

#### Public API (`apcore_a2a`)
- `serve()` — blocking one-liner to start a fully configured A2A server with uvicorn
- `async_serve()` — returns Starlette ASGI app for embedding in larger applications
- Accepts both `apcore.Registry` and `apcore.Executor` as input

#### CLI (`apcore_a2a.__main__`)
- `apcore-a2a serve` command with full argument parsing
- `--extensions-dir`, `--host`, `--port`, `--name`, `--description`, `--url`
- `--auth-type bearer`, `--auth-key` (supports literal, file path, `JWT_SECRET` env fallback)
- `--auth-issuer`, `--auth-audience`, `--push-notifications`, `--explorer`, `--cors-origins`
- `--execution-timeout`, `--log-level`
- `--version` flag

#### Observability (`/health`, `/metrics`)
- `/health` endpoint — probes task store availability, reports module count, uptime, version
- `/metrics` endpoint — active/completed/failed/canceled/input_required task counters, request count, uptime
- Request counting via Starlette middleware

#### Explorer (`apcore_a2a.explorer`)
- Optional browser UI mounted at configurable prefix (default `/explorer`)
- Skill discovery and interactive testing interface

### Dependencies
- `apcore >= 0.9.0`
- `a2a-sdk >= 0.3.20`
- `starlette >= 0.40.0`
- `uvicorn >= 0.30.0`
- `httpx >= 0.27.0`
- `PyJWT >= 2.0`
- Python >= 3.11

[0.2.0]: https://github.com/aipartnerup/apcore-a2a-python/releases/tag/v0.2.0
[0.1.0]: https://github.com/aipartnerup/apcore-a2a-python/releases/tag/v0.1.0
