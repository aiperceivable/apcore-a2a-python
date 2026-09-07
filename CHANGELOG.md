# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.0] - 2026-09-07

Minor release, version-aligned with the TypeScript and Rust SDKs. Ships the **OpenAPI
Backend** (feature F-12) and raises the required floor to `apcore>=0.30.0` /
`apcore-toolkit>=0.11.1` — which is the same change, since apcore-toolkit 0.11.0 is what
shipped the OpenAPI Scanner the feature is built on.

Suite: 449 tests (was 392), 7 skipped, `ruff check` clean.

### Added

- **`apcore_a2a.openapi_backend`** — `openapi_backend()`, plus `project_module_id`,
  `resolve_spec_location`, `synthesize_description` and
  `build_openapi_backend_from_config`. Point it at an OpenAPI 3.0/3.1 document and every
  operation becomes an A2A Skill, proxied over HTTP to the API that published it, with no
  apcore project on the other end. `openapi_backend` is re-exported from the package root.

  The pipeline is `load_spec → OpenAPIScanner.scan → HTTPProxyRegistryWriter.write →
  Registry`, all already-shipped apcore-toolkit code; everything downstream is the adapter
  that already serves an extensions directory, unmodified. See
  `apcore-a2a/docs/features/openapi-backend.md`.

- **Two repairs the composition cannot work without.** `FR-OAS-002`: apcore-toolkit derives
  module IDs into `[A-Za-z0-9_.-]` while apcore's `Registry` accepts only
  `^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$` — measured here against apcore 0.30.0 /
  apcore-toolkit 0.11.1, the canonical Swagger Petstore scans cleanly, registers **nothing**,
  and yields an Agent Card with zero skills without raising anywhere. `FR-OAS-003`: an
  operation with neither `summary` nor `description` yields `""`, and `AgentCardBuilder`
  skips empty-description modules, so undocumented operations vanished from the card with no
  diagnostic; a `{METHOD} {path}` description is synthesized instead and the affected
  modules are named at INFO.

- **`FR-OAS-005` unapproved-write warning.** The scanner never infers `requires_approval`
  for any HTTP method, and the 0.6.0 public-card filter subtracts only ACL-denied and
  approval-gated skills — so a scanned `POST /charges` is advertised on the unauthenticated
  `/.well-known/agent-card.json`. The warning names that exposure, and is **never**
  suppressed by the presence of an ACL, only by having nothing to warn about, by a module
  declaring `requires_approval` itself, or by an explicit `acknowledge_unapproved_writes`.

- **CLI:** `--from-openapi`, `--openapi-base-url`, `--openapi-prefix`, `--openapi-include`,
  `--openapi-exclude`, `--openapi-header` (repeatable `KEY:VALUE`, spec fetch only) and
  `--openapi-no-deprecated`. `--extensions-dir` is no longer required on its own; a backend
  source may come from it, from `--from-openapi`, or from `apcore-a2a.openapi.spec` in the
  config file, and naming none of the three is a usage error (exit 2, as it was when argparse
  enforced `required=True`). An extensions directory combined with an OpenAPI source requires
  a prefix, from either the flag or the config.

- **Config:** an `apcore-a2a.openapi` section, the namespace's first nested one and its first
  path-typed key. apcore 0.30.0's protections for path-typed keys do not reach a consumer
  namespace — verified: `Config.path_typed_keys()` is a fixed tuple of apcore's own five keys
  and does not change after registering a namespace with a path-valued default — so
  `resolve_spec_location` owns the three rules instead.

- **New optional dependency group `openapi`** (`apcore-toolkit[http-proxy]>=0.11.1`), for the
  spec fetch and the HTTP proxy registration.

- 57 new conformance and regression tests (`tests/conformance/test_openapi_backend.py`) against the shared
  corpus in `apcore-a2a/conformance/fixtures/openapi_backend.json`, including the fixture's
  `card_cases`, which drive the real `build_public_card` / `build_extended_card` and pin the
  exposure as a fact: an unapproved scanned write **is** on the public card, and an ACL rule
  carrying `approval: required` removes it from public while keeping it on extended.

### Fixed

Five defects found by a cross-language parity audit of the new backend, each now carrying a
regression test that was watched fail before it was watched pass.

- **The `apcore-a2a.openapi` Config Bus section was documented and read by nothing.**
  `build_openapi_backend_from_config` had no caller anywhere in `src/`, so the section the
  feature spec documents as a first-class surface — and that SRS FR-OAS-004 AC 5 states a
  requirement about — did nothing at serve time. The consequence was larger than a missing
  convenience: `timeout`, `include`, `exclude` and `acknowledge_unapproved_writes` have no CLI
  flag, so they were unreachable through *any* live path, and the last of those is the only
  configuration switch that suppresses the FR-OAS-005 public-card warning.

  The CLI now merges the section with the flags, **flag wins per key** — the precedence the
  feature spec already stated. Per key rather than per source: choosing the whole source by
  whoever named `spec` would make `--openapi-prefix` a silent no-op alongside a config-declared
  spec, which is the shape of the apcore-mcp defect this project filed upstream.

  `--openapi-no-deprecated` accordingly defaults to `None`, not `False`. With argparse's
  `store_true` default, simply *not passing* the flag would overwrite a config
  `include_deprecated: false` with `True` — an absent flag silently reversing a setting the
  operator wrote.

- **A wrong-shaped `apcore-a2a.openapi` was swallowed and the wrong error surfaced.**
  `openapi: ./spec.json` — the plausible shorthand typo for `openapi: {spec: ./spec.json}` —
  was discarded as a non-mapping, yielded no `spec`, and reached the operator as "one of
  --extensions-dir or --from-openapi is required", naming neither the key they got wrong nor
  the shape it wants. The merge now passes the value through so the message that names it is
  reachable, and that message gained the actual type (`must be a mapping, got str`). Found by
  comparing against apcore-a2a-rust, which already passed it through.

- **SECURITY: a malformed `--openapi-header` echoed its value to stderr.** The flag exists to
  carry a credential, and the commonest way to malform it is to paste the token without its
  `Key:` prefix — which put the secret in terminal scrollback and in any CI log capturing
  stderr. The message now names the expected shape and never the value. The feature spec's
  Security considerations already made this a MUST NOT, and apcore-a2a-rust already had the
  regression test; Python was the outlier.

- **A string could acknowledge unapproved writes and silence the FR-OAS-005 warning.** The
  Config Bus route read `bool(openapi_config.get("acknowledge_unapproved_writes", False))`,
  and `bool("false")` is `True` — as are `"0"` and `"no"`. A value arriving as a string from
  an `APCORE_A2A_OPENAPI_*` environment override or from quoted YAML therefore turned an
  operator's explicit refusal into an acknowledgement, suppressing the one warning that names
  the public Agent Card exposure. Now type-guarded through `_as_bool`, matching what
  TypeScript and Rust already did.

- **The same route coerced every other config value.** `float("abc")` raised at startup where
  TypeScript and Rust fall back to the default, `float("5")` accepted a shape the schema
  forbids, and a non-string `base_url` reached `HTTPProxyRegistryWriter` and failed inside
  `urlparse` instead of falling back to the document's `servers[0].url`. `_as_str` and
  `_as_float` now guard all of them.

### Changed

- Required `apcore` floor raised to `0.30.0`, `apcore-toolkit` to `0.11.1`.
- `README.md`'s Requirements block corrected — it had been stating `apcore >= 0.22.0` /
  `apcore-toolkit >= 0.8.0`, four and three floors behind `pyproject.toml` respectively.
- `tests/test_cli.py` builds its `serve` namespaces through one `_ns()` helper, so adding a
  CLI flag is a one-line change there rather than an edit at all eight call sites.

### The runtime floor (folded in from the unreleased 0.6.1)

The apcore floor itself carries no behaviour change for this package. **0.29.0** closes the
ACL pattern array's shape at every entry point, adds `caller_id` / `action` to
`ApprovalRequest`, and makes `ACL.__init__` validate the rules it is handed — this package
constructs no `ACLRule` and no `ApprovalRequest`; it reads an ACL the host supplies, through
`check_access`. **0.30.0** is confined to `Config` / `BindingLoader`: a `Config.project_root`
accessor, a declared set of path-typed configuration keys, a set-but-empty `APCORE_*` path
override now discarded, and `bindings.dir` / `bindings.pattern` as canonical defaults.

**0.30.0 does become load-bearing through F-12**, in a way that inverts what was true one
release ago. Through 0.6.x the `apcore-a2a` namespace held five scalar keys and no
path-valued one, so §9.2.1 and §9.2.2 had nothing to say about it. `apcore-a2a.openapi.spec`
is the namespace's first path-typed key, and apcore's protections for such keys do not reach
a consumer namespace — see the `Config` entry above. `--extensions-dir` remains unaffected
either way: it is an explicit CLI argument handed straight to `Registry`.

### Upgrade notes

An ACL rule whose `callers` or `targets` is `[]`, `["$or"]`, `["$not"]` or a multi-operand
`["$not", p1, p2]` is **refused at load** by apcore 0.29.0 rather than silently matching
nothing. Such a rule had been contributing nothing to the decision, so under
`default_effect: allow` it permitted the very call it named — and the public Agent Card
advertised the skill accordingly. See apcore's 0.29.0 changelog for the per-shape migration.

## [0.6.0] - 2026-09-01

Resolves `aiperceivable/apcore-a2a` issues #2, #3, #4 and #5, tracked here as #1.
One principle runs through all four: **apcore already draws these distinctions,
and a transport binding's job is to convey them, not to flatten them.**

Suite: 392 tests (was 353).
Runtime floor moves to apcore 0.28.0 / apcore-toolkit 0.10.2 (`apcore>=0.28.0` / `apcore-toolkit>=0.10.2`).

### Changed

- **A governance refusal is reported as itself** (spec srs FR-ERR-003, FR-ERR-009,
  FR-ERR-010, FR-ERR-012). `ACL_DENIED` moves from `-32001 "Task not found"` to
  `-32040 "Access denied"`; `APPROVAL_DENIED` and `APPROVAL_TIMEOUT` leave the
  `-32603` catch-all for `-32041 "Approval denied"` and `-32042 "Approval timed
  out"`. All three now reach `TASK_STATE_REJECTED` instead of
  `TASK_STATE_FAILED`, which matters most on `message/send`, where the response
  is a JSON-RPC `result` and the error code never reaches the caller at all —
  the state and its message are the entire payload.

  The old mapping told an agent a *different* failure had happened, one whose
  correct response was the opposite of the real one: `"Task not found"` sends a
  caller back to re-fetch or re-send the one thing that was fine, and
  `"Internal server error"` is the canonical *retryable* failure — for a call a
  human had explicitly refused. A2A §13.2's MUST NOT forbids revealing *the
  existence of a resource*, not the *class* of failure, so a fixed
  `"Access denied"` naming no caller, target or rule satisfies it while still
  telling an agent to stop.

  `-32001` now means only "unknown task id, or a task owned by another
  principal". `APPROVAL_PENDING` is untouched: still a resumable
  `TASK_STATE_INPUT_REQUIRED` carrying its message verbatim, which is how a
  caller learns the approval id it resumes with.

  **Breaking** for callers that matched `-32001` or the literal `"Task not
  found"` to detect an authorization failure.

- **The public Agent Card shows what an anonymous caller could actually invoke**
  (spec srs FR-AGC-003): every registered skill, minus those the ACL denies to
  the anonymous principal, minus those annotated `requires_approval`. The filter
  resolves one identity, so it runs once at card-build time — never per request
  on the auth-exempt `/.well-known/` route.

- **The extended Agent Card carries what the authenticated caller may invoke**
  (spec srs FR-AGC-004), including `requires_approval` skills, resolved against
  that caller's own identity.

- **`capabilities.extendedAgentCard` is no longer derived from `auth != null`
  alone** (spec srs FR-AGC-002, FR-AGC-006): this binding advertises the
  capability only because it now serves it.

- **Card visibility reads apcore's two governance axes apart** (spec srs
  FR-AGC-003 "The two axes" and criterion 11; FR-AGC-004 criteria 2 and 10).
  apcore 0.28.0 (`PROTOCOL_SPEC` §6.1.6) gave an ACL rule an `approval: required`
  field orthogonal to `effect`, so one check now resolves two independent results
  — may this caller reach this target, and must this call be put to a human — and
  made the legacy boolean `ACL.check` **fail closed** on the second. This binding
  filtered its cards on that boolean. Left alone, a skill the ACL *allows* the
  caller but gates behind a human would have silently vanished from the
  **extended** card too: a refusal the ACL never issued, and the caller left
  unable to learn that a capability it holds exists at all.

  Every card filter now reads `ACL.check_access` and filters on the
  authorization axis alone. The approval axis decides only *which surface*: it
  joins the module's `requires_approval` annotation as the second source the
  public card subtracts, composed by union exactly as apcore §6.9 composes them.
  Since 0.28.0 the annotation describes the *module*, not the call (apcore#110),
  so reading it alone would leave on the public card a skill an anonymous caller
  cannot in fact just call.

  The bug this closes was one line: `card_visibility.allowed_skill_ids` called
  `acl.check(...)`. `ACL.check_access` returns an `AccessDecision`, and the filter
  now reads `decision.access` for visibility and `decision.approval_required` only
  to decide which surface. Public API gains `skill_access()`; `allowed_skill_ids()`
  stays and now means the authorization axis alone.

- **apcore's `system.*` management namespace never reaches the public Agent Card**
  (spec srs FR-AGC-003 criteria 12 and 13, FR-AGC-004 criterion 11;
  `aiperceivable/apcore-a2a#5`). Removed **unconditionally** — independent of ACL
  state, of the `requires_approval` annotation, and of how `sys_modules` is
  configured. Kept on the extended card, filtered per identity like any other
  skill.

  Every other subtraction the public card makes is governance-shaped, and with no
  ACL configured they all collapse: the ACL predicates are empty and the
  annotation covers only the three `system.control.*` write modules — leaving the
  six read modules, which enumerate the deployment's module inventory, health and
  usage, published to any anonymous caller on the auth-exempt `/.well-known/`
  route. `ACL.discover()` yields nothing for a missing root by design, so "no ACL
  at all" is the default rather than an edge case, and the rule that has to hold
  there cannot be shaped like a governance verdict.

- **Warns when an unprotected control surface is served** (spec srs FR-AGC-007).
  Server construction reads apcore's `Executor.governance_state()` and warns when
  `unprotected_control_surface` is true. It never refuses to start and never
  alters a card. Withholding `system.*` from the public card removes the surface
  from *discovery*, not from *dispatch*: apcore's approval gate warns once and
  continues with no `ApprovalHandler`, so the write modules stay callable, and the
  card rule must not be mistaken for a fix to that.

### Added

- **apcore's behavioral annotations reach the wire** (spec srs FR-SKL-004):
  `readonly`, `destructive`, `idempotent` and `requires_approval` are emitted as
  namespaced entries in the standard `tags` field — `apcore:readonly`,
  `apcore:destructive`, `apcore:idempotent`, `apcore:requires-approval` — in
  that fixed order, appended after the module's own tags and de-duplicated
  against them. Only `true` flags are emitted.

  A2A 1.0 `AgentSkill` has no `extensions` and no `metadata` member, so `tags`
  is the only carrier that exists. Without them the card carried enough to
  *construct* a call and not enough to judge whether making it is safe — and
  retry semantics were unusable, since `retryable` is a property of the error
  while whether a retry is safe is a property of the operation.

- **Governance refusal errors on the client**, so a refusal is not reported as
  a transient server failure.

- `AccessDeniedError`, `ApprovalDeniedError`, `ApprovalTimeoutError` and their
  base `GovernanceRefusedError`, exported from `apcore_a2a.client`.

- **`serve(..., disclose_refusal_reason=False)`** (spec srs FR-ERR-011):
  forwards apcore's own sanitized reason for the three governance codes instead
  of the fixed per-class string. The code never changes with the flag; only the
  message does.

- `apcore_a2a.adapters.card_visibility` — `build_public_card` /
  `build_extended_card` / `allowed_skill_ids`, the shared filter behind both
  card surfaces.

### Fixed

- **`sys_modules` registered nothing** (`aiperceivable/apcore-a2a#5`). apcore reads
  `sys_modules.enabled`, a **top-level** config section; the flag was a silent
  no-op in every deployment since it was introduced.

  This binding built the registration `Config` as
  `{"apcore": {"sys_modules": {"enabled": True}}}` while apcore reads
  `config.get("sys_modules.enabled")` in legacy mode, so `register_sys_modules`
  returned at its first line — and `logger.info("Registered apcore system
  modules")` fired anyway. Operator settings found under either spelling are now
  carried through, top-level winning, and the log names the ids actually
  registered.

  Fixed together with the namespace rule above, deliberately in that order:
  repairing the config path on its own is precisely what would have opened the
  hole that rule closes.

- **`AgentCardBuilder.build_extended` no longer returns a verbatim copy.** It
  now receives the full card, and the per-caller narrowing happens in the
  `extended_card_modifier` the factory installs — `DefaultRequestHandler`'s
  `extended_agent_card` is a static message, and the answer to "what may you
  call" depends on who is asking. A client that authenticated and asked for more
  previously saw exactly what it had already been served.

## [0.5.0] - 2026-08-17

Minor release. Task-addressed methods are now scoped to the authenticated
principal, and failed tasks no longer collapse every error to a fixed string —
both from `aiperceivable/apexe` issues #33 and #34. Raises the apcore floor to
0.27.0. No breaking API change: the storage layer re-exports a2a-sdk's own
owner-scoped `TaskStore`, which already carried a `ServerCallContext`. 350 tests
pass.

### Fixed

- **Failed tasks no longer collapse every error to `"Internal server error"`.**
  `ApCoreAgentExecutor.execute` sent every code except `MODULE_TIMEOUT`,
  `EXECUTION_CANCELLED` and `APPROVAL_PENDING` to a fixed
  `"Internal server error"`, so an A2A caller could not tell a rejected argument
  from a crashed binary from a policy denial. Every apcore input guard —
  conflicting flags, option injection, control characters, schema validation —
  arrived as that one string, and `ai_guidance`, which exists to tell an agent
  what to do next, was computed and dropped.

  The failed-task text now goes through `ErrorMapper`, this package's single
  redaction policy, so the task-status surface classifies like the JSON-RPC
  surface. Internal and unrecognized errors keep the fixed string (srs
  FR-ERR-004 / FR-ERR-008; the shared `error_mapping.json` and
  `streaming_events.json` fixtures still pass unchanged) and ACL denials stay
  masked as `"Task not found"` (FR-ERR-003), but caller-fixable failures —
  schema validation, invalid input, unknown module — carry their sanitized
  detail plus `ai_guidance` when apcore supplied one. An agent that reads a
  guard refusal can now correct itself. Ported from the same fix in
  apcore-a2a-rust; `aiperceivable/apexe#33`.

  `ai_guidance` is gated on exactly those three classes, not on
  `error.user_fixable`. Six apcore codes carry `user_fixable=True` while
  mapping to the fixed string (`VERSION_CONSTRAINT_INVALID`,
  `BINDING_SCHEMA_INFERENCE_FAILED`, `BINDING_SCHEMA_MODE_CONFLICT`,
  `BINDING_STRICT_SCHEMA_INCOMPATIBLE`, `DEPENDENCY_NOT_FOUND`,
  `DEPENDENCY_VERSION_MISMATCH`), and `user_fixable` is settable per-error by
  the module author — so gating on it would let a fixed, deliberately-opaque
  string be extended with internal detail that `sanitize_message` does not
  strip (module ids, versions, env-var names, hostnames), and would let any
  module widen the `ACL_DENIED` mask. `carries_caller_detail` is the gate, and
  `test_error_mapper_message_policy_matches_to_jsonrpc_error` locks it to
  `ErrorMapper`'s own branching across every apcore error code.
- **`SCHEMA_VALIDATION_ERROR` is no longer treated as caller-fixable in every
  direction.** apcore raises the one code for input *and* output validation, so
  a module returning the wrong shape reached the caller as `-32602 Invalid
  params` with apcore's default guidance claiming `"Input validation failed"`
  and pointing at a `details.errors` field an A2A caller never receives — a
  server-side defect reported as the caller's fault. Output validation now maps
  to the fixed internal string. The direction label apcore puts at the front of
  the message is the only signal available, so that prefix is matched; anything
  unrecognized (including a module raising the code with its own wording) keeps
  the caller-facing detail. Config validation needs no arm here: apcore-python
  raises `ConfigError` / `CONFIG_INVALID` for it, which the catch-all already
  masks.

- **Task listing is `ListTasks`, not `tasks/list`.** The bundled client sent
  `tasks/list`, a name belonging to no A2A version — 1.0 calls it `ListTasks`
  and 0.3 had no listing method — so `list_tasks()` had always returned
  `-32601` against this server and against the TypeScript one, and worked only
  against this project's Rust server, which implemented the invented name. The
  client now sends `ListTasks` with the `A2A-Version: 1.0` header both upstream
  SDKs require for 1.0 method names (a request without it is read as v0.3, spec
  3.6.2). No server-side change: this server was always correct.

  The parameter names were wrong too, which only an end-to-end call could
  surface: `ListTasksRequest` declares `pageSize` / `pageToken` / `contextId` /
  `status` / `historyLength`, and has no `limit` field at all — so even with the
  method name fixed, both SDK-backed servers answered `-32602 Invalid params`.
  The Rust server had never caught it because it ignores list parameters
  entirely. `list_tasks(limit=…)` keeps `limit` as the friendly parameter name
  and sends `pageSize` on the wire.

  The factory test that covered this asserted only `status_code == 200` — and a
  JSON-RPC error is also a 200, so it passed for as long as the method was
  unroutable. It now asserts the result.

- **`ruff check` passes again.** Five lint errors had accumulated in `examples/`
  — three unsorted import blocks, one `datetime.timezone.utc` that `UP017` wants
  as `datetime.UTC`, and an over-long line in `examples/run.py`'s docstring. The
  curl example on that line was left as it is on purpose: `message/send` is the
  A2A 0.3 method name, so its payload must be in 0.3 shape (`role: "user"`, a
  `kind`-tagged part). Verified — the 1.0 shape is rejected with `-32600` on that
  method. A comment now says so, plus a note that `metadata.skillId` is needed to
  reach a module.

- **`stream_message` stops on a terminal task state instead of a `final` flag,
  and yields the event rather than the JSON-RPC envelope.** `final` is an A2A 0.3
  construct that 1.0 removed, so the old check could never fire against a 1.0
  server — the stream only ended when the connection closed. It also yielded
  each frame whole (`{jsonrpc, id, result}`) while the docstring promised the
  event, so callers had to reach into `result` themselves. Both now match the
  Rust client, which already did this: the envelope is unwrapped, and a
  `TASK_STATE_COMPLETED` / `FAILED` / `CANCELED` / `REJECTED` status ends the
  stream after being yielded. Keepalive comment lines are skipped explicitly.

  The tests that covered this had pinned the 0.3 shapes (`{"kind":"status",
  "final":true}`) and passed regardless, so they were rewritten against 1.0
  frames — including one that asserts a stray `final` does *not* end a stream.

- **A JSON-RPC error frame on an SSE stream now raises instead of being yielded
  as an event.** Upstream reports a mid-stream failure as its own frame, tagged
  `event: error` with a JSON-RPC error response in `data:`. Envelope unwrapping
  only looks for `result`, so such a frame fell through and was handed to the
  caller as though it were an event — a caller reading `statusUpdate` saw
  nothing and the failure vanished, while the non-streaming path raised for a
  byte-identical payload. Both paths now share the same error mapping, so a
  `-32001` frame produces `TaskNotFoundError` wherever it arrives. Events
  received before the error frame are still delivered.

### Security

- **All six task-addressed methods are scoped to the authenticated principal** —
  `tasks/get` / `tasks/list` (`ListTasks`) / `tasks/cancel` and
  `tasks/pushNotificationConfig/set|get|delete`. `tasks/list` previously
  returned every caller's tasks including their output; a task could be read or
  cancelled by id from any caller; and a principal holding another's task id
  could redirect that task's terminal `statusUpdate` to a webhook of its
  choosing, or silently suppress the owner's notifications by deleting their
  config. Only the unguessability of a UUIDv4 task id stood in the way. Ported
  from the same fix in apcore-a2a-rust; `aiperceivable/apexe#34`.

  a2a-sdk already had the machinery: `InMemoryTaskStore` and
  `InMemoryPushNotificationConfigStore` bucket by `OwnerResolver(context)` —
  default `resolve_user_scope`, i.e. `context.user.user_name` — and
  `DefaultRequestHandler` loads the task from that context-scoped store before
  every task-addressed method, raising `TaskNotFoundError` when it is not
  visible. It was inert because nothing supplied a `context_builder`, so every
  request carried the default `UnauthenticatedUser`. The factory now passes an
  `AuthIdentityServerCallContextBuilder` to `create_jsonrpc_routes` and
  `create_rest_routes`, which resolves the principal from the `Identity` that
  `AuthMiddleware` publishes on `auth_identity_var`.

  Cross-principal access is masked as `"Task not found"` — byte-identical to an
  unknown id, so task ids cannot be probed (srs FR-ERR-003). On the A2A 1.0 wire
  the code is `-32001`; on the v0.3 compat path a2a-sdk wraps every `A2AError`
  in `InternalError`, so the code degrades to `-32603` while the message stays
  `"Task not found"`. That is upstream's mapping, not this adapter's, and the
  responses remain indistinguishable either way.

  Callers with no `Identity` share a single `""` owner bucket, as a2a-sdk's
  `UnauthenticatedUser` does — that covers both "no authenticator configured"
  and "an authenticator configured with `require_auth=False` that did not
  authenticate this request". Single-tenant deployments are unaffected;
  configuring auth is what turns scoping on, and a permissive-mode deployment
  gets scoping only between authenticated callers.

  **Behaviour change for a custom `task_store`.** Unlike the Rust binding, which
  holds ownership in a process-local map beside the store and fails *closed*,
  ownership here lives inside the store itself. Two consequences follow, and
  they point in opposite directions:

  - a2a-sdk's `DatabaseTaskStore` carries the owner column, so scoping survives
    a restart with a persistent store — the caveat the Rust binding had to
    disclose does not apply, and no ownership map is retained beside the store,
    so nothing unbounded is introduced either.
  - **A consumer-supplied `TaskStore` that ignores its `ServerCallContext`
    argument disables scoping entirely** and fails *open*: every caller sees
    every caller's tasks, exactly as before. Upstream states the requirement as
    a SHOULD on the `TaskStore` contract ("implementations SHOULD use ... the
    authenticated caller's identity to scope data access"), so it cannot be
    enforced from here. Deployments passing `task_store=` must confirm their
    store scopes by `OwnerResolver`.

  Not covered: `message/send` and `message/stream` are not task-addressed and
  are unchanged; `tasks/resubscribe` is routed by the v0.3 compat layer to the
  same context-scoped handler and inherits the scoping, but has no test here.
  `tasks/list` under its A2A 0.3 spelling remains `-32601` — a2a-sdk maps
  neither `tasks/list` (0.3) nor anything but `ListTasks` (1.0) for that method,
  which is a pre-existing gap unrelated to scoping.

### Changed

- Required runtime bumped to `apcore >= 0.27.0` (from `>=0.26.0`). All six
  0.27.0 breaking changes were checked against this adapter; none of them
  reaches it, and all 332 pre-existing tests pass unmodified against 0.27.0.

  - **`CONFIGURATION_ERROR` renamed to `PIPELINE_CONFIGURATION_ERROR`** — a
    rename in apcore-rust and apcore-js only. apcore-python's
    `ConfigurationError` already carried `PIPELINE_CONFIGURATION_ERROR`, so
    nothing changed on this side. `ErrorMapper` never referenced either code
    (a config error reaches it through `CONFIG_NAMESPACE_DUPLICATE` /
    `CONFIG_MOUNT_ERROR` / `CONFIG_BIND_ERROR`, which are untouched).
  - **`obs.redaction.sensitive_keys` replaces rather than merges the defaults**
    — an apcore-js fix; apcore-python already behaved this way. The adapter
    configures no redaction and never constructs a `RedactionConfig`.
  - **Boolean coercion narrowed to exactly `"true"` / `"false"`** — applies to
    `SchemaValidator(coerce_types=True)`. The adapter never constructs a
    `SchemaValidator`; its own `SchemaConverter` translates JSON Schema for the
    Agent Card and does not coerce values.
  - **Unknown `pipeline.configure` keys are now a parse error** — the adapter
    declares no pipeline and calls no `build_strategy_from_config`.
  - **`_config.strict` rejects undeclared framework keys** — scoped to the
    `apcore` namespace's own framework sections. The adapter registers its
    settings under the separate, declared `apcore-a2a` namespace
    (`_config.py`), which strict mode does not police.
  - **`after_step` now fires after a recovered step body** — the adapter
    installs no step middleware. It calls `executor.use(...)` only with
    apcore's own `ObsLoggingMiddleware` / `ErrorHistoryMiddleware`, which are
    call middleware, not step middleware.

## [0.4.4] - 2026-07-14

Patch release. Bumps the required `apcore` floor to `0.26.0` to align the ecosystem on the 0.26.0 governance layer (Execution Policy §7.9, governance events, no-handler fail-loud — additive, no breaking changes). No code or API changes; all 332 tests pass unmodified against apcore 0.26.0.

## [0.4.3] - 2026-07-07

Patch release. Bumps the required `apcore-toolkit` floor to `0.10.0` (additive annotation-preservation conformance verifier; no breaking changes). No code or API changes; all 332 tests pass unmodified against apcore-toolkit 0.10.0.

## [0.4.2] - 2026-06-25

Patch release. Bumps the required apcore runtime floor to 0.25.0 and apcore-toolkit to 0.9.1. No code or API changes; all 332 tests pass unmodified against the new runtime.

### Changed

- Required runtime bumped to `apcore >= 0.25.0` (from `>=0.24.0`) and `apcore-toolkit >= 0.9.1` (from `>=0.8.1`). The adapter's public surface is unaffected by the 0.24 → 0.25 delta.

  apcore 0.25.0 and apcore-toolkit 0.9.0–0.9.1 changes reviewed for adapter impact — none required a change:
  - **Config-driven ACL discovery (0.25.0, apcore #74)** — `ACL.discover(config)` is auto-wired in `APCore.__init__`, but is skipped when the caller supplies its own `Executor` (as the adapter does), so an explicitly configured ACL is never clobbered. No behavior change for the adapter.
  - **Registry module-id constants promoted to the public surface (0.25.0, apcore #30)** — export-surface-only addition; no behavior change.
  - **apcore-toolkit OpenAPI parser hardening (0.9.0–0.9.1)** — integer status-code keys and explicit-`null` fields no longer crash `extract_output_schema` / `extract_input_schema`. No public API change; the adapter uses only `deep_resolve_refs`, which is unaffected.


## [0.4.1] - 2026-06-15

Patch release. Bumps the required apcore runtime floor to 0.24.0 and apcore-toolkit to 0.8.1. No code or API changes; all 332 tests pass unmodified against the new runtime.

### Changed

- Required runtime bumped to `apcore >= 0.24.0` (from `>=0.22.0`) and `apcore-toolkit >= 0.8.1` (from `>=0.8.0`). The adapter's public surface is unaffected by the 0.22 → 0.24 delta.

  apcore 0.23.0–0.24.0 changes reviewed for adapter impact — none required a change:
  - **Per-instance `ToggleState` (0.24.0, apcore #71)** — `Executor.__init__` and `register_sys_modules()` gained an optional `toggle_state` parameter. The adapter's existing call sites (`Executor(registry)`, `register_sys_modules(registry, executor, config)`) use the back-compat form and fall back to the process-global toggle state — behaviorally identical for a single-registry server.
  - **`CircuitBreakerMiddleware` constructor rewrite (0.23.0, breaking)** — not used by the adapter.
  - **AI error-recovery metadata auto-populated on `ModuleError` (0.23.0)** — `user_fixable` / `ai_guidance` now flow through `ModuleError.to_dict()` automatically; the adapter never backfilled them, so no change is needed (they now surface for free).
  - **`A2ASubscriber` 4xx no-retry (0.23.0)** — applies to apcore's own event-system subscriber, not this adapter.


## [0.4.0] - 2026-06-01

### Changed

- **A2A protocol upgraded 0.3 → 1.0 (BREAKING)** — migrated to `a2a-sdk >= 1.0.0` (protobuf-based `a2a.types.a2a_pb2`):
  - All types are protobuf: `Part(text=…)` / inspection via `part.WhichOneof("content")`; `TaskState.TASK_STATE_*` and `Role.ROLE_*` enum values; `TaskStatus.timestamp` is a protobuf `Timestamp`.
  - Events lost the `final` flag and the 0.3 `type`/`kind` discriminator; the executor emits a `Task` event before any `TaskStatusUpdateEvent` (a2a-sdk 1.0 requirement).
  - `AgentCard`: `url` → `supported_interfaces` (`AgentInterface(url, protocol_binding="JSONRPC", protocol_version="1.0")`); `capabilities` gains `extended_agent_card`; security via the proto `security_schemes` map.
  - Agent Card served at `/.well-known/agent-card.json` (+ `/.well-known/agent.json` 0.3 alias); JSON-RPC routes use `enable_v0_3_compat=True`.
- **`apcore` dependency** bumped to `>=0.22.0`; **added `apcore-toolkit >=0.8.0`** (schema `$ref` resolution via `deep_resolve_refs`).
- **New apcore 0.22 capabilities wired** — real streaming via `Executor.stream()`, cooperative cancellation via `CancelToken`, `global_deadline` (from `execution_timeout`), `ObsLoggingMiddleware`, and `register_sys_modules` (new `sys_modules` option on `serve()` / `async_serve()`).
- **Env prefix** — `APCORE__A2A` (double underscore) → `APCORE_A2A` (single underscore).
- **`PartConverter`** serializes lists and scalars with compact JSON separators (`,`/`:`) so artifact text is byte-identical to the TypeScript and Rust adapters.

### Added

- **Error Formatter Registry** (§8.8) — `ErrorMapper` now implements the `ErrorFormatter` protocol and registers with `ErrorFormatterRegistry.register("a2a", ...)` during factory initialization, making the A2A error formatter discoverable by the ecosystem.
- **Config Bus namespace** (§9.13) — new `_config.py` module registers the `apcore-a2a` namespace with env prefix `APCORE_A2A` and defaults for `execution_timeout`, `cors_origins`, `explorer`, `metrics`, `push_notifications`.
- **New error codes** in `ErrorMapper` — `MODULE_DISABLED` (→ "Module is currently disabled"), `CONFIG_NAMESPACE_DUPLICATE`, `CONFIG_MOUNT_ERROR`, `CONFIG_BIND_ERROR` (→ "Configuration error").
- **`format()` method** on `ErrorMapper` — implements the `ErrorFormatter` protocol, delegating to `to_jsonrpc_error()`.
- **Cross-language conformance suite** (`tests/conformance/`) mirroring the shared fixtures, and an Apache-2.0 **`LICENSE`**.
- A2A 1.0 migration covered by the full suite (incl. conformance) — **332 tests passing**.

---

## [0.3.0] - 2026-03-27

### Added

- **Display overlay in `SkillMapper`** (§5.13) — `to_skill()` reads `metadata["display"]["a2a"]` for skill name, description, tags, and guidance.
  - Skill name: `a2a.alias` → `display.alias` → humanized `module_id`.
  - Description: `a2a.description` → `display.description` → `module.description`. Guidance appended if present.
  - Tags: `display.tags` → `module.tags`.

### Changed

- **`apcore` dependency** bumped from `>=0.9.0` to `>=0.14.0`.
- **Environment variables** renamed with `APCORE_` prefix: `JWT_SECRET` → `APCORE_JWT_SECRET`, `A2A_EXECUTION_TIMEOUT` → `APCORE_A2A_EXECUTION_TIMEOUT`.

### Removed

- **`_build_extensions()` dead code** — `AgentSkill` has no `extensions` field in the A2A SDK; this method could never be wired in. Deleted along with its 3 tests.

### Tests

- 6 display overlay tests + 3 empty-string fallthrough tests for cross-language parity with TypeScript.
- Removed 3 `test__build_extensions_*` tests (dead code).

---

## [0.2.1] - 2026-03-22

### Changed
- Rebrand: aipartnerup → aiperceivable

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
- `--auth-type bearer`, `--auth-key` (supports literal, file path, `APCORE_JWT_SECRET` env fallback)
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

[0.2.0]: https://github.com/aiperceivable/apcore-a2a-python/releases/tag/v0.2.0
[0.1.0]: https://github.com/aiperceivable/apcore-a2a-python/releases/tag/v0.1.0
