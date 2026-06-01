"""Launch A2A agent server with binding.yaml modules — zero code intrusion demo.

Usage:
    PYTHONPATH=./examples/binding_demo python examples/binding_demo/run.py

Then open http://127.0.0.1:8000/explorer/ in your browser.
"""

from apcore import BindingLoader, Executor, Registry

from apcore_a2a import serve

# 1. Load modules from binding.yaml files (myapp.py stays untouched)
registry = Registry()
loader = BindingLoader()
modules = loader.load_binding_dir("./examples/binding_demo/extensions", registry)
print(f"Loaded {len(modules)} module(s) from binding files")

# 2. Create executor (needed by A2A server for skill execution)
executor = Executor(registry)

print()
print("Explorer UI:  http://127.0.0.1:8000/explorer/")
print("Agent Card:   http://127.0.0.1:8000/.well-known/agent-card.json")
print()

# 3. Launch A2A server with Explorer UI
serve(
    executor,
    host="127.0.0.1",
    port=8000,
    explorer=True,
)
