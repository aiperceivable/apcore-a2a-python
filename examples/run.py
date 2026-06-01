"""Launch A2A agent server with all example modules — class-based + binding.yaml.

Usage (from the project root):
    PYTHONPATH=./examples/binding_demo python examples/run.py

Then open http://127.0.0.1:8000/explorer/ in your browser.

Enable JWT authentication by setting JWT_SECRET:
    JWT_SECRET=my-secret PYTHONPATH=./examples/binding_demo python examples/run.py

Then test with curl:
    # Agent card (always accessible; 0.3 alias /.well-known/agent.json also served)
    curl http://localhost:8000/.well-known/agent-card.json

    # Send a message (JSON-RPC)
    curl -X POST http://localhost:8000/ \\
      -H "Content-Type: application/json" \\
      -d '{"jsonrpc":"2.0","id":1,"method":"message/send","params":{"message":{"role":"user","messageId":"msg-1","parts":[{"kind":"text","text":"Hello!"}]}}}'
"""

import os

from apcore import BindingLoader, Executor, Registry

from apcore_a2a import serve
from apcore_a2a.auth import JWTAuthenticator

# 1. Discover class-based modules from extensions/
registry = Registry(extensions_dir="./examples/extensions")
n_class = registry.discover()

# 2. Load binding.yaml modules into the same registry
loader = BindingLoader()
binding_modules = loader.load_binding_dir("./examples/binding_demo/extensions", registry)

# 3. Create executor (needed by A2A server for skill execution)
executor = Executor(registry)

print(f"Class-based modules: {n_class}")
print(f"Binding modules:     {len(binding_modules)}")
print(f"Total:               {len(registry.module_ids)}")

# 4. Build JWT authenticator if JWT_SECRET is set
auth = None
jwt_secret = os.environ.get("JWT_SECRET")
if jwt_secret:
    auth = JWTAuthenticator(key=jwt_secret)
    print("JWT authentication:  enabled (HS256)")
    # Generate a sample token for testing
    import jwt as pyjwt

    sample_token = pyjwt.encode(
        {"sub": "demo-user", "type": "user", "roles": ["admin"]},
        jwt_secret,
        algorithm="HS256",
    )
    print(f"Sample token:        {sample_token}")
else:
    print("JWT authentication:  disabled (set JWT_SECRET to enable)")

print()
print("Explorer UI:         http://127.0.0.1:8000/explorer/")
print("Agent Card:          http://127.0.0.1:8000/.well-known/agent-card.json")
print()

# 5. Launch A2A server with Explorer UI
serve(
    executor,
    host="127.0.0.1",
    port=8000,
    explorer=True,
    auth=auth,
)
