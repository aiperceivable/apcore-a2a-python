"""Conformance — Algorithm A-OAS: OpenAPI backend parity (feature F-12).

Fixture: ``conformance/fixtures/openapi_backend.json`` (shared verbatim with the
TypeScript and Rust runners). Builds a Registry from each document through
:func:`apcore_a2a.openapi_backend.openapi_backend` and asserts the registered
module set, the repaired descriptions, the emitted diagnostics, and the resulting
Agent Card.

The scanner's own derivation is pinned by apcore-toolkit's corpus, not here. What
this driver checks is everything the binding adds on top.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

pytest.importorskip("apcore_toolkit")

from apcore_a2a.openapi_backend import (  # noqa: E402
    openapi_backend,
    project_module_id,
    resolve_spec_location,
)

from ._spec import load_fixture  # noqa: E402

_FIXTURE = load_fixture("openapi_backend.json")


def _ids(case: dict[str, Any]) -> str:
    return case["id"]


def _build(case: dict[str, Any], **overrides: Any) -> Any:
    options = dict(case.get("options") or {})
    # The fixture spells a pseudo-option that names the *situation*, not a kwarg.
    other_source = options.pop("additional_backend_source", False)
    # No base_url default here: `no_base_url_anywhere_rejected` exists precisely to
    # assert the failure, and injecting one would delete the case's premise.
    return openapi_backend(
        case["document"],
        has_other_backend_source=other_source,
        **options,
        **overrides,
    )


def _registry_ids(registry: Any) -> list[str]:
    return sorted(registry.list(visibility=["public", "hidden"]))


# --------------------------------------------------------------------------
# test_cases — document -> registered modules
# --------------------------------------------------------------------------


def _lines_at(caplog: pytest.LogCaptureFixture, level: int) -> list[str]:
    """Messages logged at exactly `level`.

    Scoping by level matters: capturing at DEBUG and then asserting against the
    whole buffer makes every "this must be a WARNING" claim vacuous, because a
    demotion to `debug()` still lands in the same text.
    """
    return [r.getMessage() for r in caplog.records if r.levelno == level]


@pytest.mark.parametrize("case", _FIXTURE["test_cases"], ids=_ids)
def test_modules(case: dict[str, Any], caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        registry = _build(case)

    expected = case["expected_modules"]
    assert _registry_ids(registry) == sorted(m["module_id"] for m in expected)

    for spec in expected:
        definition = registry.get_definition(spec["module_id"])
        assert definition is not None, f"{spec['module_id']} not registered"
        assert definition.description == spec["description"]

        for field, want in (spec.get("annotations") or {}).items():
            got = getattr(definition.annotations, field, None)
            assert got == want, f"{spec['module_id']}.{field}: {got!r} != {want!r}"

    # A dropped operation must be reported at WARNING: the projection runs inside
    # a transform_module hook, and a hook returning None drops it silently.
    warnings = _lines_at(caplog, logging.WARNING)
    for drop in case.get("expected_dropped") or []:
        line = next(
            (w for w in warnings if drop["derived_id"] in w),
            None,
        )
        assert line is not None, (
            f"no WARNING names the dropped id {drop['derived_id']!r}; got {warnings}"
        )
        # The segment is a substring of the derived id, so asserting both against
        # the same line proves nothing. Remove the id first: what remains must
        # still name the segment, or the operator cannot tell WHY it was dropped.
        assert drop["offending_segment"] in line.replace(drop["derived_id"], ""), (
            f"the drop WARNING names {drop['derived_id']!r} but never names the "
            f"offending segment {drop['offending_segment']!r} on its own: {line!r}"
        )

    for substring in case.get("expected_warning_substrings") or []:
        assert any(substring in w for w in warnings), (
            f"missing {substring!r} in WARNING lines: {warnings}"
        )

    for module_id in case.get("expected_on_agent_card") or []:
        definition = registry.get_definition(module_id)
        assert definition.description.strip(), (
            f"{module_id} has an empty description and AgentCardBuilder would skip it"
        )


@pytest.mark.parametrize(
    "case",
    [c for c in _FIXTURE["test_cases"] if any("description_was_synthesized" in m for m in c["expected_modules"])],
    ids=_ids,
)
def test_description_repair_flag(case: dict[str, Any], caplog: pytest.LogCaptureFixture) -> None:
    """The INFO line must name every operation whose description was synthesized.

    The assertion is scoped to the synthesis line itself, not to the whole log.
    apcore-toolkit's writer emits its own ``Registered HTTP proxy: <projected id>``
    line, so a naive ``module_id in caplog.text`` is satisfied by that and passes
    even when the synthesis report names the **pre**-projection id — which is
    exactly the defect FR-OAS-003 criterion 5 exists to forbid.
    """
    with caplog.at_level(logging.DEBUG):
        registry = _build(case)

    synthesis = [line for line in _lines_at(caplog, logging.INFO) if "synthesized" in line]

    for spec in case["expected_modules"]:
        if "description_was_synthesized" not in spec:
            continue
        if spec["description_was_synthesized"]:
            assert len(synthesis) == 1, (
                f"expected exactly one synthesis INFO line, got {synthesis}"
            )
            assert spec["module_id"] in synthesis[0], (
                f"the synthesis report does not name {spec['module_id']!r} (the "
                f"post-projection id that reaches the card): {synthesis[0]!r}"
            )
        else:
            assert not synthesis, f"the repair fired when it should not have: {synthesis}"
        assert registry.get_definition(spec["module_id"]).description == spec["description"]


# --------------------------------------------------------------------------
# warning_cases — FR-OAS-005
# --------------------------------------------------------------------------


@pytest.mark.parametrize("case", _FIXTURE["warning_cases"], ids=_ids)
def test_unapproved_write_warning(
    case: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        _build(case)

    warnings = "\n".join(
        r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING
    )
    fired = "PUBLIC Agent Card" in warnings

    assert fired is case["expect_warning"], (
        f"expected warning={case['expect_warning']}, got:\n{warnings}"
    )
    for substring in case.get("expected_warning_substrings") or []:
        assert substring.lower() in warnings.lower(), (
            f"missing {substring!r} in:\n{warnings}"
        )


def test_permissive_acl_does_not_suppress_the_warning() -> None:
    """The discriminating case, restated as a standalone regression.

    apcore's ``GovernanceState.unprotected_control_surface`` reports the absence of
    a gate, never the presence of protection. An implementation that gates this
    warning on ``acl_configured`` passes every fixture case but this one.
    """
    case = next(
        c
        for c in _FIXTURE["warning_cases"]
        if c["id"] == "write_warning_not_suppressed_by_permissive_acl"
    )
    assert case["acl"]["default_effect"] == "allow"
    assert case["expect_warning"] is True


# --------------------------------------------------------------------------
# config_cases — FR-OAS-004
# --------------------------------------------------------------------------


@pytest.mark.parametrize("case", _FIXTURE["config_cases"], ids=_ids)
def test_spec_location(
    case: dict[str, Any], caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir("/")  # a CWD that is never the expected answer

    with caplog.at_level(logging.WARNING):
        resolved = resolve_spec_location(
            case["spec_value"], project_root=case["project_root"]
        )
        if resolved is None and "spec_value_next_tier" in case:
            resolved = resolve_spec_location(
                case["spec_value_next_tier"], project_root=case["project_root"]
            )

    assert resolved == case["expected_resolved_spec"]

    if "expected_warning_substring" in case:
        assert case["expected_warning_substring"] in caplog.text


# --------------------------------------------------------------------------
# card_cases — the exposure FR-OAS-005 warns about, pinned as a fact
# --------------------------------------------------------------------------


class _AclOnlyExecutor:
    """The minimum surface `card_visibility` reads off an apcore Executor."""

    def __init__(self, acl: Any = None) -> None:
        self._acl = acl


def _acl_from(spec: dict[str, Any] | None) -> Any:
    if not spec:
        return None
    from apcore.acl import ACL, ACLRule

    # apcore-python spells `approval` as a plain string defaulting to
    # "not_required"; apcore-rust uses an `ApprovalRequirement` enum. The fixture
    # carries the wire spelling, and each language's driver maps it.
    rules = [
        ACLRule(
            callers=list(raw["callers"]),
            targets=list(raw["targets"]),
            effect=raw["effect"],
            approval=raw.get("approval") or "not_required",
        )
        for raw in spec["rules"]
    ]
    return ACL(rules=rules, default_effect=spec["default_effect"])


@pytest.mark.parametrize("case", _FIXTURE["card_cases"], ids=_ids)
def test_agent_card_visibility(case: dict[str, Any]) -> None:
    """A scanned write operation reaches the PUBLIC card unless an ACL gates it.

    Pinned as a fact so a future change to card visibility cannot silently alter
    the exposure. The remedy case is the reason the backend does not withhold
    scanned write operations as a class.
    """
    from a2a.types import AgentCapabilities
    from apcore.context import Identity

    from apcore_a2a.adapters.agent_card import AgentCardBuilder
    from apcore_a2a.adapters.card_visibility import build_extended_card, build_public_card
    from apcore_a2a.adapters.skill_mapper import SkillMapper

    registry = _build(case)
    executor = _AclOnlyExecutor(_acl_from(case.get("acl")))

    card = AgentCardBuilder(SkillMapper()).build(
        registry,
        name="agent",
        description="d",
        version="1.0.0",
        url="http://localhost:8000",
        capabilities=AgentCapabilities(streaming=False, push_notifications=False),
    )

    public = build_public_card(card, executor, registry)
    extended = build_extended_card(card, executor, Identity(id="u1", type="service"))

    assert sorted(s.id for s in public.skills) == sorted(
        case["expected_public_card_skills"]
    )
    assert sorted(s.id for s in extended.skills) == sorted(
        case["expected_extended_card_skills"]
    )


# --------------------------------------------------------------------------
# error_cases
# --------------------------------------------------------------------------


@pytest.mark.parametrize("case", _FIXTURE["error_cases"], ids=_ids)
def test_errors(case: dict[str, Any]) -> None:
    from apcore import Registry

    registry = None
    preexisting = case.get("preexisting_registry_module_ids")
    if preexisting:
        registry = Registry()
        for module_id in preexisting:
            _register_stub(registry, module_id)

    with pytest.raises((ValueError, RuntimeError, Exception)) as excinfo:
        _build(case, registry=registry)

    message = str(excinfo.value)
    for substring in case["expected_error_substrings"]:
        assert substring in message, f"missing {substring!r} in {message!r}"

    if "expected_registry_module_ids_after" in case:
        assert _registry_ids(registry) == sorted(
            case["expected_registry_module_ids_after"]
        ), "the preflight must leave the registry byte-for-byte unchanged"


def _register_stub(registry: Any, module_id: str) -> None:
    """A minimal registered module, so a collision has something to collide with."""
    from apcore.decorator import module as apcore_module

    @apcore_module(id=module_id, description=f"stub {module_id}", registry=registry)
    def _stub(value: str = "") -> str:  # pragma: no cover - never invoked
        return value


# --------------------------------------------------------------------------
# projection unit coverage (FR-OAS-002)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("listPets", "listpets"),
        ("pet-store.items.get", "pet_store.items.get"),
        ("already.legal", "already.legal"),
        ("v1.2fa.get", None),
        ("Users.UserId.Get", "users.userid.get"),
        ("9lives", None),
        # Python's `$` also matches before a trailing newline, so `re.match` would
        # accept this and register a module whose ID carries one. Reachable from a
        # caller's own `derive_module_id` hook, a supported public option.
        # TypeScript and Rust both reject it.
        ("abc\n", None),
        ("a.b\n", None),
    ],
)
def test_project_module_id(raw: str, expected: str | None) -> None:
    assert project_module_id(raw) == expected


@pytest.mark.parametrize(
    ("spec", "root", "expected"),
    [
        ("./openapi.json", "/srv/project", "/srv/project/openapi.json"),
        ("a/./b.json", "/srv/project", "/srv/project/a/b.json"),
        # pathlib drops `.` but keeps `..`, so a bare join left this as
        # `/srv/project/../openapi.json` while TypeScript's `path.resolve` and
        # Rust's lexical normalizer both produced `/srv/openapi.json`.
        ("../openapi.json", "/srv/project", "/srv/openapi.json"),
        ("/etc/apcore/openapi.json", "/srv/project", "/etc/apcore/openapi.json"),
    ],
)
def test_relative_spec_is_lexically_normalized(spec: str, root: str, expected: str) -> None:
    """Normalization must be lexical, matching the other two SDKs.

    `Path.resolve()` would touch the filesystem and follow symlinks, diverging in
    the other direction for a path that need not exist.
    """
    assert resolve_spec_location(spec, project_root=root) == expected


# --------------------------------------------------------------------------
# Config Bus coercion (FR-OAS-005 AC 3) — cross-language parity regressions
# --------------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["false", "0", "no", "", "off"])
def test_a_string_never_acknowledges_unapproved_writes(raw: str) -> None:
    """A truthy-string read would silence the FR-OAS-005 safety warning.

    `bool("false")` is `True`, and a Config Bus value arrives as a string from an
    `APCORE_A2A_OPENAPI_*` environment override or from quoted YAML — so a
    coercing read turns an operator's explicit "no" into an acknowledgement.
    TypeScript and Rust both type-guard; this pins Python to the same rule.
    """
    from apcore_a2a.openapi_backend import _as_bool

    assert _as_bool(raw, False) is False


@pytest.mark.parametrize(
    ("value", "default", "expected"),
    [
        (True, False, True),
        (False, True, False),
        (None, True, True),
        (1, False, False),  # an int is not a bool here, unlike bool(1)
        ("true", False, False),  # a string never acknowledges, in either direction
    ],
)
def test_as_bool_accepts_only_real_booleans(value: object, default: bool, expected: bool) -> None:
    from apcore_a2a.openapi_backend import _as_bool

    assert _as_bool(value, default) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(5, 5.0), (2.5, 2.5), ("5", 30.0), ("abc", 30.0), (None, 30.0), (True, 30.0)],
)
def test_as_float_ignores_non_numbers(value: object, expected: float) -> None:
    """`float("abc")` raises and `float("5")` accepts a shape the schema forbids.

    Both diverge from TypeScript and Rust, which ignore a non-number and fall
    back to the default.
    """
    from apcore_a2a.openapi_backend import _as_float

    assert _as_float(value, 30.0) == expected


def test_malformed_openapi_header_is_rejected_without_echoing_the_value(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The flag carries a credential, so the error must not quote what it got.

    The commonest way to malform `--openapi-header` is to paste the token without
    its `Key:` prefix; echoing it puts the secret in terminal scrollback and in
    any CI log that captures stderr. The feature spec's Security considerations
    make this a MUST NOT, and apcore-a2a-rust already had this regression test.
    """
    from apcore_a2a.__main__ import _parse_headers

    secret = "supersecrettoken-do-not-echo"  # noqa: S105 - a test fixture, not a real key
    with pytest.raises(SystemExit) as excinfo:
        _parse_headers([secret])

    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert secret not in captured.err, "the malformed value was echoed to stderr"
    assert secret not in captured.out
    assert "KEY:VALUE" in captured.err


def test_wellformed_openapi_headers_parse() -> None:
    from apcore_a2a.__main__ import _parse_headers

    assert _parse_headers(["X-Api-Key: abc", "X-Tenant:t1"]) == {
        "X-Api-Key": "abc",
        "X-Tenant": "t1",
    }
    assert _parse_headers(None) is None


# --------------------------------------------------------------------------
# Config Bus wiring (FR-OAS-004 AC 5) — the route must be reachable at all
# --------------------------------------------------------------------------


def _ns_for(**overrides: Any) -> Any:
    """A `serve` Namespace with every OpenAPI flag absent (None)."""
    from argparse import Namespace

    base: dict[str, Any] = {
        "extensions_dir": None,
        "from_openapi": None,
        "openapi_base_url": None,
        "openapi_prefix": None,
        "openapi_include": None,
        "openapi_exclude": None,
        "openapi_headers": None,
        "openapi_no_deprecated": None,
    }
    base.update(overrides)
    return Namespace(**base)


def test_config_bus_alone_supplies_a_backend_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The `apcore-a2a.openapi` section must be readable with no CLI flag at all.

    Before this wiring the section was documented in the feature spec and read by
    nothing: `build_openapi_backend_from_config` had no caller anywhere in `src/`,
    so `timeout`, `include`, `exclude` and `acknowledge_unapproved_writes` — none
    of which has a CLI flag — were unreachable through any live path.
    """
    from apcore_a2a import __main__ as cli

    monkeypatch.setattr(
        cli, "_parse_headers", lambda _raw: None
    )  # isolate from the header parser
    monkeypatch.setattr(
        "apcore_a2a._config.get_a2a_setting",
        lambda key, fallback=None: (
            {"spec": "./from-config.json", "timeout": 5.0, "prefix": "cfg"}
            if key == "openapi"
            else fallback
        ),
    )

    merged = cli._merge_openapi_settings(_ns_for())
    assert isinstance(merged, dict), "the Config Bus section was not consulted"
    assert merged["spec"] == "./from-config.json"
    assert merged["timeout"] == 5.0, "a key with no CLI flag must survive"
    assert merged["prefix"] == "cfg"


def test_an_explicit_flag_beats_the_config_bus_per_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per key, not per source.

    Choosing the whole source by whoever named `spec` would make
    `--openapi-prefix` a silent no-op alongside a config-declared spec — the same
    shape as the apcore-mcp `--openapi-header` defect this binding filed upstream.
    """
    from apcore_a2a import __main__ as cli

    monkeypatch.setattr(
        "apcore_a2a._config.get_a2a_setting",
        lambda key, fallback=None: (
            {"spec": "./from-config.json", "prefix": "cfg", "timeout": 5.0}
            if key == "openapi"
            else fallback
        ),
    )

    merged = cli._merge_openapi_settings(_ns_for(openapi_prefix="from-flag"))
    assert isinstance(merged, dict)
    assert merged["prefix"] == "from-flag", "the flag must win"
    assert merged["spec"] == "./from-config.json", "config keys with no flag survive"
    assert merged["timeout"] == 5.0


def test_an_absent_store_true_flag_does_not_override_the_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--openapi-no-deprecated` defaults to None, not False.

    With an argparse `store_true` default of `False`, simply *not passing* the flag
    would overwrite a config `include_deprecated: false` with `True` — an absent
    flag silently reversing a setting the operator wrote.
    """
    from apcore_a2a import __main__ as cli

    monkeypatch.setattr(
        "apcore_a2a._config.get_a2a_setting",
        lambda key, fallback=None: (
            {"spec": "./s.json", "include_deprecated": False} if key == "openapi" else fallback
        ),
    )

    absent = cli._merge_openapi_settings(_ns_for())
    assert isinstance(absent, dict)
    assert absent["include_deprecated"] is False, "an absent flag must not override"

    given = cli._merge_openapi_settings(_ns_for(openapi_no_deprecated=True))
    assert isinstance(given, dict)
    assert given["include_deprecated"] is False


def test_a_wrong_shaped_section_is_not_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`openapi: ./spec.json` must reach the error that names the shape.

    Discarding a non-mapping section here makes it yield no `spec`, so the
    operator is told "one of --extensions-dir or --from-openapi is required" —
    the wrong error, naming neither the key they got wrong nor the shape it
    wants. `build_openapi_backend_from_config` owns the right message; the merge
    has to pass the value through for it to be reachable.

    Found by comparing against apcore-a2a-rust, which passes it through.
    """
    from apcore_a2a import __main__ as cli
    from apcore_a2a.openapi_backend import build_openapi_backend_from_config

    monkeypatch.setattr(
        "apcore_a2a._config.get_a2a_setting",
        lambda key, fallback=None: ("./spec.json" if key == "openapi" else fallback),
    )

    merged = cli._merge_openapi_settings(_ns_for())
    assert merged == "./spec.json", "the wrong-shaped section was swallowed"

    # ... and the value it passes through produces the message that names the shape.
    with pytest.raises(ValueError, match="must be a mapping, got str"):
        build_openapi_backend_from_config(merged)


def test_no_spec_anywhere_is_not_an_openapi_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apcore_a2a import __main__ as cli

    monkeypatch.setattr(
        "apcore_a2a._config.get_a2a_setting", lambda key, fallback=None: fallback
    )
    assert cli._merge_openapi_settings(_ns_for()) is None
    # A section with no `spec` is equally not a source.
    monkeypatch.setattr(
        "apcore_a2a._config.get_a2a_setting",
        lambda key, fallback=None: ({"prefix": "p"} if key == "openapi" else fallback),
    )
    assert cli._merge_openapi_settings(_ns_for()) is None


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ({"http_method": "get", "url_path": "/pets"}, "GET /pets"),
        ({"http_method": "GET"}, "GET"),
        ({"url_path": "/pets"}, "/pets"),
        # Non-strings are malformed metadata, not values to render. `str(123)`
        # would put a bare number on the public Agent Card as if it were an HTTP
        # method, and TypeScript's `String(false)` produced a literal "FALSE".
        # Rust's `as_str()` always treated these as absent; all three now agree.
        ({"http_method": 123, "url_path": "/pets"}, "/pets"),
        ({"http_method": False, "url_path": "/pets"}, "/pets"),
        ({"http_method": "GET", "url_path": 0}, "GET"),
        ({}, "m"),
    ],
)
def test_synthesize_description_reads_strings_only(
    metadata: dict[str, Any], expected: str
) -> None:
    class _Module:
        def __init__(self, md: dict[str, Any]) -> None:
            self.metadata = md
            self.module_id = "m"

    from apcore_a2a.openapi_backend import synthesize_description

    assert synthesize_description(_Module(metadata)) == expected


@pytest.mark.parametrize(
    ("needle", "where"),
    [
        ("^[a-z][a-z0-9_]*$", "the drop WARNING must name the pattern a segment must match"),
        ("derive_module_id", "the drop WARNING must name the remedy"),
    ],
)
def test_drop_warning_carries_the_canonical_facts(
    needle: str, where: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Per the spec's Canonical diagnostic text table.

    "the derived module ID has a segment (`2fa`) apcore's registry cannot accept"
    tells the operator what failed and not what would succeed — `2fa` is rejected
    for beginning with a digit, which is not guessable without the pattern. Rust
    carried both facts; Python and TypeScript did not.
    """
    case = next(
        c
        for c in _FIXTURE["test_cases"]
        if c["id"] == "projection_unprojectable_segment_dropped_with_warning"
    )
    with caplog.at_level(logging.WARNING):
        _build(case)

    drops = [w for w in _lines_at(caplog, logging.WARNING) if "skipping OpenAPI operation" in w]
    assert len(drops) == 1
    assert needle in drops[0], f"{where}: {drops[0]!r}"


def test_collision_error_says_nothing_was_registered() -> None:
    """The operator has to be told the registry is untouched.

    Without it they cannot tell a fatal preflight from a partial write, which is
    the difference between "fix the prefix and restart" and "inspect what landed".
    TypeScript and Rust carried the sentence; Python did not.
    """
    from apcore import Registry

    case = next(
        c
        for c in _FIXTURE["error_cases"]
        if c["id"] == "id_collision_against_registry_rejected_atomically"
    )
    registry = Registry()
    for module_id in case["preexisting_registry_module_ids"]:
        _register_stub(registry, module_id)

    with pytest.raises(ValueError, match="Nothing was registered"):
        _build(case, registry=registry)


def test_no_base_url_error_says_what_breaks() -> None:
    """Naming the missing key is not the same as naming the consequence."""
    case = next(
        c for c in _FIXTURE["error_cases"] if c["id"] == "no_base_url_anywhere_rejected"
    )
    with pytest.raises(ValueError, match="unknown host"):
        _build(case)
