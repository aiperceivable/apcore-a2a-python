# Examples

Runnable demos of **apcore-a2a** with the A2A Explorer UI.

```
examples/
├── run.py                     # Unified launcher (all 5 modules)
├── extensions/                # Class-based apcore modules
│   ├── text_echo.py
│   ├── math_calc.py
│   └── greeting.py
└── binding_demo/              # Zero-code binding demo
    ├── myapp.py               # Plain business logic (NO apcore imports)
    ├── extensions/
    │   ├── convert_temperature.binding.yaml
    │   └── word_count.binding.yaml
    └── run.py                 # Binding-only launcher
```

## Quick Start (all modules together)

Both class-based modules and binding.yaml modules load into the same Registry and coexist as A2A skills.

```bash
# From the project root
pip install -e .

PYTHONPATH=./examples/binding_demo python examples/run.py
```

Open http://127.0.0.1:8000/explorer/ — you should see all 5 skills.

## Run class-based modules only

```bash
apcore-a2a serve \
  --extensions-dir ./examples/extensions \
  --explorer
```

No `PYTHONPATH` needed. Uses the built-in CLI directly.

## Run binding modules only

```bash
PYTHONPATH=./examples/binding_demo python examples/binding_demo/run.py
```

## All Modules

| Module | Type | Description |
|--------|------|-------------|
| `text_echo` | class-based | Echo text back, optionally uppercase |
| `math_calc` | class-based | Basic arithmetic (add, sub, mul, div) |
| `greeting` | class-based | Personalized greeting in different styles |
| `convert_temperature` | binding.yaml | Celsius / Fahrenheit / Kelvin conversion |
| `word_count` | binding.yaml | Count words, characters, and lines |

## Two Integration Approaches

| | Class-based | Binding YAML |
|---|---|---|
| Your code changes | Write apcore module class | **None** |
| Schema definition | Pydantic `BaseModel` | YAML `input_schema` / `output_schema` |
| Launch | CLI `--extensions-dir` | Python script with `BindingLoader` |
| Best for | New projects | Existing projects with functions to expose |

## Using the Explorer UI

The Explorer UI at http://127.0.0.1:8000/explorer/ lets you:

1. **View Agent Card** — See agent metadata, capabilities, and version
2. **Browse Skills** — Expand each skill to see its description, tags, input/output modes, and examples
3. **Send Messages** — Select a skill and send a message via `message/send` (JSON-RPC)
4. **Stream Messages** — Watch real-time SSE events via `message/stream`
5. **Inspect Tasks** — Fetch task state or cancel running tasks

### Sending a message

1. Select a skill from the dropdown (e.g., `text_echo`)
2. Type a message: `Echo this text please`
3. Click **Send** or press `Ctrl+Enter`
4. The JSON-RPC response appears below with the task result

### Streaming

1. Select a skill and type a message
2. Click **Stream** to see SSE events in real time
3. Watch status transitions: `submitted` → `working` → `completed`

## JWT Authentication

Enable JWT authentication by setting the `JWT_SECRET` environment variable:

```bash
JWT_SECRET=my-secret PYTHONPATH=./examples/binding_demo python examples/run.py
```

### Test Token

Pre-generated token (secret: `my-secret`, algorithm: HS256):

```
eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJkZW1vLXVzZXIiLCJ0eXBlIjoidXNlciIsInJvbGVzIjpbImFkbWluIl19.yOFQMlZnMZwXg6KoJX61sCm2VbCzmqtT8dFRNsOhaZM
```

Payload:

```json
{"sub": "demo-user", "type": "user", "roles": ["admin"]}
```

### Verify with cURL

```bash
TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJkZW1vLXVzZXIiLCJ0eXBlIjoidXNlciIsInJvbGVzIjpbImFkbWluIl19.yOFQMlZnMZwXg6KoJX61sCm2VbCzmqtT8dFRNsOhaZM"

# Agent card (always accessible; 0.3 alias /.well-known/agent.json also served)
curl http://localhost:8000/.well-known/agent-card.json

# Send message without auth
curl -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"message/send","params":{"message":{"role":"user","messageId":"msg-1","parts":[{"kind":"text","text":"Hello!"}]}}}'

# Send message with auth
curl -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"jsonrpc":"2.0","id":1,"method":"message/send","params":{"message":{"role":"user","messageId":"msg-1","parts":[{"kind":"text","text":"Hello!"}]}}}'
```

### Explorer UI with JWT

The Explorer UI at http://127.0.0.1:8000/explorer/ is always accessible without authentication. The agent card and skill browser work without a token. Message sending and streaming will include the auth token stored in `sessionStorage` if available.

## Comparing with apcore-mcp

The same apcore modules work with both protocols:

```bash
# Serve as A2A agent
apcore-a2a serve --extensions-dir ./examples/extensions --explorer

# Serve as MCP server (using apcore-mcp)
apcore-mcp serve --extensions-dir ./examples/extensions --transport streamable-http --explorer --allow-execute
```

Same modules, same Registry, different protocols.
