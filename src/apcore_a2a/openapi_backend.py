"""OpenAPI backend — serve an OpenAPI 3.0/3.1 document as A2A Skills.

Pipeline::

    load_spec -> OpenAPIScanner.scan -> [skip illegal IDs, repair descriptions]
              -> HTTPProxyRegistryWriter.write -> Registry

The scanner and the writer live in apcore-toolkit; this module composes them and
adds the two things the composition needs on top:

* **FR-OAS-002 registry-legal module IDs.** apcore-toolkit >= 0.13.0 emits every
  ``module_id`` in apcore's Canonical ID alphabet (camelCase split into
  snake_case words, other characters replaced by ``_``, a legal ID never
  rewritten), after ``base_path_prefix`` and the hooks — so this module registers
  the emitted ID unchanged. The one thing the toolkit will not repair is a
  segment that begins with a digit (``/v1/2fa`` -> ``v1.2fa.get``): such a module
  is skipped before the writer, with a WARNING naming the ID and the segment.
* **FR-OAS-003 description repair.** An operation with neither ``summary`` nor
  ``description`` yields ``""``, and ``AgentCardBuilder`` skips a module whose
  description is empty — so the operation would vanish from the Agent Card with
  no diagnostic.

Both run on the modules ``scan`` *returns* — after the caller's own
``transform_module`` hook, the toolkit's normalisation, its filters and its
deduplication — so every diagnostic names the ID that actually reaches the
Agent Card.

See ``apcore-a2a/docs/features/openapi-backend.md`` for the specification and
``conformance/fixtures/openapi_backend.json`` for the shared contract.
"""

from __future__ import annotations

import logging
import os
import re
import warnings
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "MODULE_ID_SEGMENT",
    "WRITE_METHODS",
    "build_openapi_backend_from_config",
    "openapi_backend",
    "project_module_id",
    "resolve_spec_location",
    "synthesize_description",
]

#: An apcore module-ID segment. Enforced by ``Registry.register`` and again by
#: ``Executor.call``; a segment may not begin with a digit, which is why some
#: derived IDs cannot be repaired at all. The FR-OAS-002 skip policy tests every
#: segment of an emitted ID against this.
#:
#: Matched with :meth:`re.fullmatch`, never :meth:`re.match`. Python's ``$`` also
#: matches *before* a trailing newline, so ``re.match`` would accept ``"abc\n"``
#: and register a module whose ID carries a newline — reachable from a caller's
#: own ``derive_module_id`` hook, which is a supported public option. TypeScript's
#: ``$`` (no ``/m``) and Rust's char-class check both reject it.
MODULE_ID_SEGMENT = re.compile(r"[a-z][a-z0-9_]*")

#: HTTP methods that change state. The population FR-OAS-005 warns about.
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

_URL_SCHEMES = ("http://", "https://")


def project_module_id(module_id: str) -> str | None:
    """Project a toolkit-derived module ID into apcore's registry alphabet.

    .. deprecated::
        apcore-toolkit >= 0.13 emits every ``module_id`` in apcore's Canonical ID
        alphabet itself, so this projection is no longer needed and the backend
        no longer calls it. It will be removed in a later minor release. Note that
        it does not reproduce the toolkit's naming: it lowercases without
        splitting words (``listPets`` -> ``listpets``, where the toolkit emits
        ``list_pets``).

    Lowercase, then ``-`` -> ``_``. Returns ``None`` when the result still has a
    segment apcore would reject — such an ID cannot be repaired without inventing
    one.
    """
    warnings.warn(
        "project_module_id is deprecated: apcore-toolkit >= 0.13 emits module IDs in "
        "apcore's Canonical ID alphabet, so the projection is no longer needed. It "
        "will be removed in a later minor release.",
        DeprecationWarning,
        stacklevel=2,
    )
    candidate = module_id.lower().replace("-", "_")
    if all(MODULE_ID_SEGMENT.fullmatch(seg) for seg in candidate.split(".")):
        return candidate
    return None


def _illegal_segment(module_id: str) -> str | None:
    """The first segment of ``module_id`` apcore's registry would reject, else ``None``.

    Tested on the ID exactly as the scanner emitted it — never a projection of it.
    An empty ID yields the empty segment ``""``, matching the toolkit's own
    legality warning.
    """
    for seg in module_id.split("."):
        if not MODULE_ID_SEGMENT.fullmatch(seg):
            return seg
    return None


def synthesize_description(module: Any) -> str:
    """Build a ``{METHOD} {path}`` description for an undocumented operation.

    Uses the ``http_method`` / ``url_path`` metadata keys ``HTTPProxyRegistryWriter``
    already requires, so the value is factual and stable across scans. Deliberately
    terse so it reads as a placeholder rather than as documentation.
    """
    metadata = getattr(module, "metadata", None) or {}
    # String-only, never a coercion. `str(123)` would put a bare number on the
    # public Agent Card as if it were an HTTP method, and `str(False)` would put
    # "FALSE" there. A non-string here means the metadata is malformed — reachable
    # from a caller's own `transform_operation` hook or a vendor extension — and
    # the honest answer is to treat the field as absent. Rust's `as_str()` already
    # did this; Python and TypeScript were the two that coerced.
    raw_method = metadata.get("http_method")
    raw_path = metadata.get("url_path")
    method = raw_method.strip().upper() if isinstance(raw_method, str) else ""
    path = raw_path.strip() if isinstance(raw_path, str) else ""
    if method and path:
        return f"{method} {path}"
    if method:
        return method
    return path or str(getattr(module, "module_id", "") or "operation")


def _resolve_project_root(explicit: str | None) -> str:
    """The base a relative ``spec`` resolves against (FR-OAS-004 rule 3)."""
    if explicit:
        return explicit
    try:  # pragma: no cover - depends on host configuration
        from apcore.config import Config

        root = Config.load(validate=False).project_root
        if root:
            return str(root)
    except Exception:  # noqa: BLE001 - a missing/unloadable Config is not fatal here
        logger.debug("Could not read Config.project_root; falling back to CWD")
    return str(Path.cwd())


def resolve_spec_location(spec: Any, *, project_root: str | None = None) -> Any:
    """Resolve ``apcore-a2a.openapi.spec`` (FR-OAS-004).

    apcore 0.30.0 declared the closed set of path-typed configuration keys and the
    base a relative one resolves against, but ``Config.path_typed_keys()`` is a
    fixed tuple of apcore's own keys and never consults a namespace registered
    through ``Config.register_namespace`` — verified against apcore 0.30.0. This
    binding therefore owns the three rules rather than inheriting them.

    1. A value beginning ``http://`` / ``https://`` is a URL, used verbatim.
    2. A set-but-empty value is discarded with a WARNING; the caller falls through
       to the next configuration tier. It is never joined to a base, which would
       silently yield the project root.
    3. A relative path resolves against ``Config.project_root`` — not the process
       CWD, and not the document's own directory.
    """
    if spec is None:
        return None
    if not isinstance(spec, str | Path):
        # An already-parsed document. Nothing to resolve.
        return spec

    raw = str(spec)
    if raw.strip() == "":
        logger.warning(
            "apcore-a2a.openapi.spec is set but empty; discarding it and falling "
            "through to the next configuration tier. An empty value is not a path."
        )
        return None

    if raw.startswith(_URL_SCHEMES):
        return raw

    path = Path(raw)
    if path.is_absolute():
        return str(path)
    # `os.path.normpath`, not `Path.resolve()`. `resolve()` touches the filesystem
    # and follows symlinks, which would diverge from TypeScript's `path.resolve`
    # and Rust's hand-rolled lexical normalizer for a path that need not exist.
    # A bare `Path(root) / path` is not enough either: pathlib drops `.` but keeps
    # `..`, so `../openapi.json` stayed `/srv/project/../openapi.json` here while
    # both other SDKs produced `/srv/openapi.json`.
    return os.path.normpath(str(Path(_resolve_project_root(project_root)) / path))


def _document_server_url(document: Any) -> str | None:
    """``servers[0].url``, when it is a usable absolute URL."""
    if not isinstance(document, dict):
        return None
    servers = document.get("servers")
    if not isinstance(servers, list) or not servers:
        return None
    first = servers[0]
    if not isinstance(first, dict):
        return None
    url = first.get("url")
    if isinstance(url, str) and url.startswith(_URL_SCHEMES):
        return url
    return None


def _registry_ids(registry: Any) -> list[str]:
    """Every module ID in ``registry``, hidden ones included."""
    try:
        return list(registry.list(visibility=["public", "hidden"]))
    except TypeError:  # pragma: no cover - older Registry signatures
        return list(registry.list())


def _warn_unapproved_writes(
    modules: list[Any],
    *,
    acknowledge: bool,
    governance_state: Any = None,
) -> None:
    """FR-OAS-005 — the unapproved-write warning.

    Reports the **absence of a gate, never the presence of protection**, which is
    the rule apcore's own ``GovernanceState.unprotected_control_surface`` states:
    a wired ACL that permits every call still yields ``False``. So an attached ACL
    never suppresses this warning — it only softens the wording when at least one
    rule carries ``approval: required``.
    """
    if acknowledge:
        return

    unapproved = [
        m
        for m in modules
        if str((getattr(m, "metadata", None) or {}).get("http_method", "")).upper() in WRITE_METHODS
        and not getattr(getattr(m, "annotations", None), "requires_approval", False)
    ]
    if not unapproved:
        return

    methods = sorted({str((getattr(m, "metadata", None) or {}).get("http_method", "")).upper() for m in unapproved})
    ids = ", ".join(sorted(str(m.module_id) for m in unapproved)[:10])

    # Only ONE tier is decidable here, and it is decidable only when a caller has
    # explicitly handed us a GovernanceState. At backend-construction time the
    # Executor does not exist yet — this function builds the Registry the Executor
    # is later built *from* — so "does an ACL rule carry approval: required" is
    # genuinely unknowable, not merely unimplemented. That question belongs to
    # FR-AGC-007's serve-time warning, which runs where the Executor does exist.
    gate_wired = getattr(governance_state, "builtin_approval_gate_wired", None)
    if gate_wired is False:
        lead = (
            "the approval gate is NOT in the execution pipeline under the active "
            "strategy, so neither a module annotation nor an ACL rule's "
            "`approval: required` would fire for"
        )
    else:
        lead = "no module-level approval requirement is declared for"

    logger.warning(
        "apcore-a2a: %s %d scanned write operation(s) (%s). They will be advertised "
        "on the PUBLIC Agent Card at /.well-known/agent-card.json, which is served "
        "without authentication. Configure an ACL rule carrying `approval: required`, "
        "set requires_approval via a transform_module hook, or set "
        "apcore-a2a.openapi.acknowledge_unapproved_writes: true to record this as "
        "intended. Affected: %s",
        lead,
        len(unapproved),
        "/".join(methods),
        ids,
    )


def openapi_backend(
    spec: Any,
    *,
    base_url: str | None = None,
    prefix: str | None = None,
    include: str | None = None,
    exclude: str | None = None,
    include_deprecated: bool = True,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
    auth_header_factory: Callable[[], dict[str, str]] | None = None,
    registry: Any | None = None,
    has_other_backend_source: bool = False,
    project_root: str | None = None,
    acknowledge_unapproved_writes: bool = False,
    governance_state: Any = None,
    transform_operation: Callable[..., Any] | None = None,
    transform_module: Callable[[Any], Any] | None = None,
    derive_module_id: Callable[..., str | None] | None = None,
) -> Any:
    """Build an apcore ``Registry`` from an OpenAPI 3.0/3.1 document.

    ``timeout`` is the **spec-fetch** timeout in seconds, never the per-call proxy
    timeout — the two are different concerns and apcore-mcp conflates them in Rust.
    """
    try:
        from apcore import Registry
        from apcore_toolkit import HTTPProxyRegistryWriter
        from apcore_toolkit.openapi_scanner import OpenAPIScanner, load_spec
    except ImportError as exc:  # pragma: no cover - exercised by the extras matrix
        raise RuntimeError(
            "The OpenAPI backend needs apcore-toolkit with its HTTP proxy support. "
            "Install `apcore-toolkit[http-proxy]` (or `apcore-a2a[openapi]`)."
        ) from exc

    # Checked FIRST, before any fetch or scan: the scanner deduplicates within one
    # scan only and knows nothing about modules already in the registry, so a
    # misconfiguration here must fail without a network round trip.
    if has_other_backend_source and not prefix:
        raise ValueError(
            "apcore-a2a.openapi.prefix is required when another backend source is "
            "also configured: without it a derived module ID can collide with a "
            "project module ID."
        )

    resolved = resolve_spec_location(spec, project_root=project_root)
    if resolved is None:
        raise ValueError("apcore-a2a.openapi.spec is required and resolved to nothing.")

    document = (
        resolved if not isinstance(resolved, str | Path) else load_spec(resolved, headers=headers, timeout=timeout)
    )

    # The caller's own transform_module is handed to the scanner as it is, so it
    # runs FIRST: everything below operates on what `scan` returns, after that
    # hook, the toolkit's normalisation, its filters and its deduplication.
    scanned = OpenAPIScanner().scan(
        document,
        include=include,
        exclude=exclude,
        base_path_prefix=prefix,
        include_deprecated=include_deprecated,
        transform_operation=transform_operation,
        derive_module_id=derive_module_id,
        transform_module=transform_module,
    )

    skipped: list[tuple[str, str]] = []
    synthesized: list[str] = []
    modules: list[Any] = []
    for module in scanned:
        module_id = str(module.module_id)

        # FR-OAS-002: apcore-toolkit >= 0.13 emits the Canonical ID alphabet, so
        # the emitted ID is registered unchanged — never projected again. It
        # leaves exactly one thing unrepaired (a segment beginning with a digit,
        # or an empty ID from a hook), and that module is skipped HERE, before
        # the writer: handed to the writer, apcore's registry would reject it as
        # a write failure, and every diagnostic below would count it. Checked on
        # the returned ID, never inside transform_module, where a hook's
        # `MyThing` has not yet been normalised to `my_thing`.
        segment = _illegal_segment(module_id)
        if segment is not None:
            skipped.append((module_id, segment))
            continue

        # FR-OAS-003: repair the description before the module can reach a card
        # filter that would silently drop it. Recorded under the EMITTED id — the
        # one on the Agent Card, dedup suffix included.
        if not str(getattr(module, "description", "") or "").strip():
            module = replace(module, description=synthesize_description(module))
            synthesized.append(module_id)
        modules.append(module)

    for module_id, segment in skipped:
        logger.warning(
            "apcore-a2a: skipping OpenAPI operation %r — the derived module ID has a "
            "segment (%r) apcore's registry cannot accept (it must match "
            "^[a-z][a-z0-9_]*$), and it cannot be repaired without inventing an ID. "
            "Supply a derive_module_id or transform_module hook to name this "
            "operation yourself.",
            module_id,
            segment,
        )
    # Scanner warnings are re-emitted for the modules that will register. A
    # skipped module's own legality warning from the toolkit says what the skip
    # WARNING above already said, so it is not repeated.
    for module in modules:
        for warning in getattr(module, "warnings", None) or []:
            logger.warning("apcore-a2a: %s: %s", module.module_id, warning)
    if not modules:
        logger.warning(
            "apcore-a2a: the OpenAPI document produced no registrable modules; the " "Agent Card will have no skills."
        )
    if synthesized:
        logger.info(
            "apcore-a2a: %d of %d scanned operations had no summary or description; a "
            '"{METHOD} {path}" description was synthesized so they appear on the Agent '
            "Card. Affected: %s",
            len(synthesized),
            len(scanned),
            ", ".join(sorted(synthesized)),
        )

    target = registry if registry is not None else Registry()

    # Full-set preflight before the first write. Toolkit writers report per-module
    # WriteResults and never abort, so without this a duplicate would arrive as a
    # failed WriteResult, get logged and skipped, and leave a partial registry.
    existing = set(_registry_ids(target))
    collisions = sorted({str(m.module_id) for m in modules} & existing)
    if collisions:
        raise ValueError(
            "OpenAPI-derived module IDs collide with modules already in the registry: "
            f"{', '.join(collisions)}. Nothing was registered. Set "
            "apcore-a2a.openapi.prefix to namespace them."
        )

    resolved_base = base_url or _document_server_url(document)
    if not resolved_base:
        raise ValueError(
            "No base_url: the document has no usable absolute servers[0].url, so "
            "every proxied call would resolve against an unknown host. Set "
            "apcore-a2a.openapi.base_url."
        )

    writer = HTTPProxyRegistryWriter(
        base_url=resolved_base,
        auth_header_factory=auth_header_factory,
    )
    for result in writer.write(modules, target):
        if getattr(result, "verification_error", None):
            logger.error(
                "apcore-a2a: %s failed to register as an HTTP proxy: %s",
                result.module_id,
                result.verification_error,
            )

    _warn_unapproved_writes(
        modules,
        acknowledge=acknowledge_unapproved_writes,
        governance_state=governance_state,
    )
    return target


def _as_bool(value: Any, default: bool) -> bool:
    """A config value is a boolean only if it *is* one.

    Never `bool(value)`. `bool("false")`, `bool("0")` and `bool("no")` are all
    `True`, and a Config Bus value arrives as a string from an `APCORE_A2A_*`
    environment override or from quoted YAML — so a coercing read turns
    ``acknowledge_unapproved_writes: "false"`` into an acknowledgement and
    silences the FR-OAS-005 warning the operator was trying to keep. TypeScript
    and Rust both type-guard here; this is the reference implementation matching
    them, not diverging from them.
    """
    return value if isinstance(value, bool) else default


def _as_str(value: Any) -> str | None:
    """A config value is a string only if it *is* one, else absent."""
    return value if isinstance(value, str) else None


def _as_float(value: Any, default: float) -> float:
    """A config value is a number only if it *is* one, else the default.

    `float("abc")` raises and `float("5")` silently accepts a string the schema
    does not allow; both diverge from TypeScript and Rust, which ignore a
    non-number and fall back.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return default
    return float(value)


def build_openapi_backend_from_config(
    openapi_config: Any,
    *,
    registry: Any | None = None,
    has_other_backend_source: bool = False,
    governance_state: Any = None,
) -> Any | None:
    """Build the backend from an ``apcore-a2a.openapi`` Config Bus section.

    Returns ``None`` when the section is absent or falsy, so a caller can treat
    "no OpenAPI configured" as an ordinary outcome.
    """
    if not openapi_config:
        return None
    if not isinstance(openapi_config, dict):
        raise ValueError("apcore-a2a.openapi must be a mapping, got " f"{type(openapi_config).__name__}.")

    spec = openapi_config.get("spec")
    if spec is None or (isinstance(spec, str) and not spec.strip()):
        raise ValueError("apcore-a2a.openapi.spec is required.")

    # Resolve the project root HERE rather than leaving it to the default: this is
    # the route most deployments use, and leaving it unset is what makes
    # apcore-mcp's TypeScript and Rust config routes resolve against the CWD.
    return openapi_backend(
        spec,
        base_url=_as_str(openapi_config.get("base_url")),
        prefix=_as_str(openapi_config.get("prefix")),
        include=_as_str(openapi_config.get("include")),
        exclude=_as_str(openapi_config.get("exclude")),
        include_deprecated=_as_bool(openapi_config.get("include_deprecated"), True),
        headers=openapi_config.get("headers"),
        timeout=_as_float(openapi_config.get("timeout"), 30.0),
        registry=registry,
        has_other_backend_source=has_other_backend_source,
        project_root=_resolve_project_root(None),
        acknowledge_unapproved_writes=_as_bool(openapi_config.get("acknowledge_unapproved_writes"), False),
        governance_state=governance_state,
    )
