"""Task-addressed methods are scoped to the authenticated principal (apexe #34).

a2a-sdk scopes task storage by an owner resolved from the ``ServerCallContext``
(``resolve_user_scope`` -> ``context.user.user_name``), and
``DefaultRequestHandler`` loads the task from that context-scoped store before
every task-addressed method. Nothing supplied a ``context_builder``, so every
request carried the default ``UnauthenticatedUser`` and every caller shared one
owner bucket: ``tasks/list`` returned every caller's tasks including their full
stdout, and any principal holding another's task id could read it, cancel it,
or redirect its terminal ``statusUpdate`` to a webhook of its choosing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from apcore import Identity
from starlette.testclient import TestClient

from apcore_a2a.server.factory import A2AServerFactory

ALICE = "alice"
BOB = "bob"


@dataclass
class _Descriptor:
    """Minimal registry descriptor (the conftest stub is not importable here)."""

    module_id: str = "echo"
    description: str = "Echo a payload back"
    input_schema: dict[str, Any] | None = field(default_factory=lambda: {"type": "object"})
    output_schema: dict[str, Any] | None = field(default_factory=lambda: {"type": "object"})
    name: str | None = None
    documentation: str | None = None
    version: str | None = None
    tags: list[str] = field(default_factory=list)
    annotations: Any = None
    examples: list[Any] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class _BearerIsPrincipal:
    """Authenticator whose bearer token *is* the principal id."""

    def authenticate(self, headers: dict[str, str]) -> Identity | None:
        token = headers.get("authorization", "").removeprefix("Bearer ").strip()
        return Identity(id=token, type="user") if token else None

    def security_schemes(self) -> dict:
        return {"bearerAuth": {"type": "http", "scheme": "bearer"}}


@pytest.fixture
def client() -> TestClient:
    registry = MagicMock()
    registry.list.return_value = ["echo"]
    registry.get_definition.return_value = _Descriptor()
    executor = MagicMock()
    executor.call_async = AsyncMock(return_value={"result": "ok"})
    del executor.stream  # force the single-shot path

    app, _ = A2AServerFactory().create(
        registry,
        executor,
        name="Scoping Agent",
        description="d",
        version="1",
        url="http://localhost",
        auth=_BearerIsPrincipal(),
        push_notifications=True,
    )
    return TestClient(app)


def _rpc(client: TestClient, who: str, method: str, params: dict, *, v1: bool = False) -> dict:
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {who}"}
    if v1:
        # a2a-sdk treats a request with no A2A-Version header as v0.3 (spec
        # section 3.6.2), so the 1.0 method names need it explicitly.
        headers["A2A-Version"] = "1.0"
    body = json.dumps({"jsonrpc": "2.0", "id": "1", "method": method, "params": params})
    return client.post("/", content=body, headers=headers).json()


def _submit(client: TestClient, who: str, message_id: str) -> str:
    """Run one task as ``who`` and return its id."""
    response = _rpc(
        client,
        who,
        "message/send",
        {
            "message": {
                "role": "user",
                "messageId": message_id,
                "parts": [{"kind": "text", "text": "{}"}],
                "metadata": {"skillId": "echo"},
            }
        },
    )
    assert "result" in response, response
    return response["result"]["id"]


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def test_tasks_get_hides_another_principals_task(client):
    alice_task = _submit(client, ALICE, "m-alice")

    assert _rpc(client, ALICE, "tasks/get", {"id": alice_task})["result"]["id"] == alice_task

    denied = _rpc(client, BOB, "tasks/get", {"id": alice_task})["error"]
    unknown = _rpc(client, BOB, "tasks/get", {"id": "00000000-0000-0000-0000-000000000000"})["error"]
    # Masked as "not found", not "forbidden" (srs FR-ERR-003): a caller must not
    # learn that another principal's task id exists. The two responses are
    # identical, so task ids cannot be probed.
    assert denied == unknown
    assert denied["message"] == "Task not found"


def test_tasks_get_returns_minus_32001_on_the_1_0_wire(client):
    """The masking code is -32001, exactly like an unknown id.

    On the v0.3 compat path a2a-sdk wraps every ``A2AError`` in ``InternalError``,
    so the code degrades to -32603 while the message stays "Task not found" —
    upstream's behaviour, not this adapter's. Both responses remain
    indistinguishable from an unknown id either way, which is the property that
    matters.
    """
    alice_task = _submit(client, ALICE, "m-alice")

    denied = _rpc(client, BOB, "GetTask", {"id": alice_task}, v1=True)["error"]
    unknown = _rpc(client, BOB, "GetTask", {"id": "no-such-task"}, v1=True)["error"]
    assert denied["code"] == -32001
    assert denied["message"] == "Task not found"
    assert denied == unknown


def test_tasks_list_returns_only_the_callers_own_tasks(client):
    alice_one = _submit(client, ALICE, "m-a1")
    alice_two = _submit(client, ALICE, "m-a2")
    bob_task = _submit(client, BOB, "m-b1")

    alice_ids = {t["id"] for t in _rpc(client, ALICE, "ListTasks", {}, v1=True)["result"]["tasks"]}
    bob_ids = {t["id"] for t in _rpc(client, BOB, "ListTasks", {}, v1=True)["result"]["tasks"]}

    assert alice_ids == {alice_one, alice_two}
    assert bob_ids == {bob_task}
    # The defect this closes: bob could read the full stdout of alice's tasks.
    assert bob_task not in alice_ids


def test_tasks_cancel_is_scoped_to_the_owner(client):
    alice_task = _submit(client, ALICE, "m-alice")

    denied = _rpc(client, BOB, "CancelTask", {"id": alice_task}, v1=True)["error"]
    assert denied["code"] == -32001
    assert denied["message"] == "Task not found"


# ---------------------------------------------------------------------------
# Push notification configs
# ---------------------------------------------------------------------------


def _push_config(task_id: str, config_id: str, url: str) -> dict:
    return {
        "taskId": task_id,
        "pushNotificationConfig": {"id": config_id, "url": url},
    }


def test_push_notification_config_set_is_scoped_to_the_owner(client):
    """The worst of the six: a redirect of somebody else's terminal statusUpdate."""
    alice_task = _submit(client, ALICE, "m-alice")

    owner = _rpc(
        client,
        ALICE,
        "tasks/pushNotificationConfig/set",
        _push_config(alice_task, "cfg-alice", "https://alice.example/hook"),
    )
    assert owner["result"]["taskId"] == alice_task

    attacker = _rpc(
        client,
        BOB,
        "tasks/pushNotificationConfig/set",
        _push_config(alice_task, "cfg-evil", "https://attacker.example/hook"),
    )
    assert attacker["error"]["message"] == "Task not found"


def test_push_notification_config_get_and_delete_are_scoped_to_the_owner(client):
    alice_task = _submit(client, ALICE, "m-alice")
    _rpc(
        client,
        ALICE,
        "tasks/pushNotificationConfig/set",
        _push_config(alice_task, "cfg-alice", "https://alice.example/hook"),
    )
    params = {"id": alice_task, "pushNotificationConfigId": "cfg-alice"}

    assert _rpc(client, ALICE, "tasks/pushNotificationConfig/get", params)["result"]["taskId"] == alice_task
    assert _rpc(client, BOB, "tasks/pushNotificationConfig/get", params)["error"]["message"] == "Task not found"
    # Deleting the owner's config would silently suppress their notifications.
    assert _rpc(client, BOB, "tasks/pushNotificationConfig/delete", params)["error"]["message"] == "Task not found"
    # The owner's config survived the attempt.
    assert _rpc(client, ALICE, "tasks/pushNotificationConfig/get", params)["result"]["taskId"] == alice_task


# ---------------------------------------------------------------------------
# Degradation without an authenticator
# ---------------------------------------------------------------------------


def test_without_an_authenticator_every_caller_shares_one_owner_bucket():
    """Documented degradation, matching a2a-sdk's own ``UnauthenticatedUser``.

    ``resolve_user_scope`` returns ``context.user.user_name``, which is ``""``
    for an unauthenticated caller. A single-tenant deployment is therefore
    unaffected by this change, and configuring auth is what turns scoping on.
    """
    registry = MagicMock()
    registry.list.return_value = ["echo"]
    registry.get_definition.return_value = _Descriptor()
    executor = MagicMock()
    executor.call_async = AsyncMock(return_value={"result": "ok"})
    del executor.stream

    app, _ = A2AServerFactory().create(
        registry,
        executor,
        name="Open Agent",
        description="d",
        version="1",
        url="http://localhost",
    )
    client = TestClient(app)

    task_id = _submit(client, "", "m-anon-1")
    # A second, differently-credentialed caller sees it, because with no
    # authenticator configured there is only one principal.
    assert _rpc(client, "someone-else", "tasks/get", {"id": task_id})["result"]["id"] == task_id
