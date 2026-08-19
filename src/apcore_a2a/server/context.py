"""ServerCallContext construction — binds the authenticated principal to task scoping.

a2a-sdk scopes every task-addressed operation by an *owner* resolved from the
``ServerCallContext``: ``InMemoryTaskStore`` and
``InMemoryPushNotificationConfigStore`` both bucket by
``OwnerResolver(context)``, whose default ``resolve_user_scope`` returns
``context.user.user_name``, and ``DefaultRequestHandler`` loads the task from
that context-scoped store before ``tasks/get``, ``tasks/cancel``,
``ListTasks`` and all four ``tasks/pushNotificationConfig/*`` methods.

That machinery was inert here because nothing supplied a ``context_builder``:
every request built a ``ServerCallContext`` with the default
``UnauthenticatedUser`` (``user_name == ""``), so every caller shared one owner
bucket. ``ListTasks`` returned every caller's tasks including their full
stdout, any principal could read or cancel another's task by id, and any
principal could point another's terminal ``statusUpdate`` at a webhook of its
choosing or delete the owner's push config. Only the unguessability of a UUIDv4
task id stood in the way.
"""

from __future__ import annotations

from typing import Any

from a2a.auth.user import UnauthenticatedUser, User
from a2a.server.context import ServerCallContext
from a2a.server.routes import DefaultServerCallContextBuilder
from starlette.requests import Request

from apcore_a2a.auth.middleware import auth_identity_var


class IdentityUser(User):
    """Adapts an apcore ``Identity`` to a2a-sdk's ``User`` interface.

    ``user_name`` is the identity id, which is what ``resolve_user_scope`` uses
    as the owner key — the same principal the executor puts on the apcore
    ``Context``, so governance and task scoping name the same caller.
    """

    def __init__(self, identity: Any) -> None:
        self._identity = identity

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def user_name(self) -> str:
        return str(self._identity.id)


class AuthIdentityServerCallContextBuilder(DefaultServerCallContextBuilder):
    """Builds a ``ServerCallContext`` carrying the authenticated principal.

    ``AuthMiddleware`` publishes the authenticated apcore ``Identity`` on
    ``auth_identity_var`` before the route runs, so the identity is available
    here on the same task context.

    Callers with no ``Identity`` fall back to ``UnauthenticatedUser``, whose
    ``user_name`` is ``""`` — a single shared owner bucket. That covers both
    "no authenticator configured" and "an authenticator configured with
    ``require_auth=False`` that did not authenticate this request".
    Single-tenant deployments are therefore unaffected; a permissive-mode
    deployment gets scoping only between authenticated callers, with every
    unauthenticated caller sharing one bucket.
    """

    def build_user(self, request: Request) -> User:
        identity = auth_identity_var.get()
        if identity is None:
            return super().build_user(request)
        return IdentityUser(identity)


def anonymous_context() -> ServerCallContext:
    """A ``ServerCallContext`` for the shared unauthenticated owner bucket.

    Used by in-process call sites that have no HTTP request to build from (the
    ``/health`` store probe). Explicit so those sites cannot accidentally read
    an authenticated principal's tasks.
    """
    return ServerCallContext(user=UnauthenticatedUser())
