"""CLI entry point: apcore-a2a serve ..."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from apcore_a2a import __version__


def main() -> None:
    """Launch apcore-a2a CLI."""
    parser = argparse.ArgumentParser(
        prog="apcore-a2a",
        description="Launch an A2A agent server from apcore modules",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command")

    serve_parser = subparsers.add_parser("serve", help="Start A2A server")
    serve_parser.add_argument("--extensions-dir", default=None)
    serve_parser.add_argument(
        "--from-openapi",
        default=None,
        dest="from_openapi",
        help="OpenAPI 3.0/3.1 spec URL or path; every operation becomes an A2A Skill",
    )
    serve_parser.add_argument("--openapi-base-url", default=None, dest="openapi_base_url")
    serve_parser.add_argument("--openapi-prefix", default=None, dest="openapi_prefix")
    serve_parser.add_argument("--openapi-include", default=None, dest="openapi_include")
    serve_parser.add_argument("--openapi-exclude", default=None, dest="openapi_exclude")
    serve_parser.add_argument(
        "--openapi-header",
        action="append",
        default=None,
        dest="openapi_headers",
        metavar="KEY:VALUE",
        help="Header for the spec fetch only; repeatable. Never sent on proxied calls",
    )
    serve_parser.add_argument(
        "--openapi-no-deprecated",
        action="store_true",
        default=None,
        dest="openapi_no_deprecated",
        help="Skip operations marked deprecated: true",
    )
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)
    serve_parser.add_argument("--name", default=None)
    serve_parser.add_argument("--description", default=None)
    serve_parser.add_argument("--version-str", default=None, dest="agent_version")
    serve_parser.add_argument("--url", default=None)
    serve_parser.add_argument("--auth-type", choices=["bearer"], default=None)
    serve_parser.add_argument("--auth-key", default=None)
    serve_parser.add_argument("--auth-issuer", default=None)
    serve_parser.add_argument("--auth-audience", default=None)
    serve_parser.add_argument("--push-notifications", action="store_true")
    serve_parser.add_argument("--explorer", action="store_true")
    serve_parser.add_argument("--cors-origins", nargs="*", default=None)
    serve_parser.add_argument("--execution-timeout", type=int, default=300)
    serve_parser.add_argument(
        "--log-level",
        choices=["debug", "info", "warning", "error"],
        default="info",
    )

    args = parser.parse_args()

    if args.command == "serve":
        # A backend source may also come from the Config Bus, so the usage check
        # has to consult it — otherwise a valid `apcore-a2a.openapi.spec` in the
        # config file would be rejected for naming no flag.
        # Resolved once and passed down: this reads the config file and validates
        # the `--openapi-header` flags, and doing it again inside `_run_serve`
        # would parse the file twice and re-run that validation. TypeScript and
        # Rust both compute it once for the same reason.
        openapi = _merge_openapi_settings(args)
        if not args.extensions_dir and not args.from_openapi and not openapi:
            # A usage error, so it exits 2 like every other argparse usage error —
            # `--extensions-dir` alone was `required=True` before the OpenAPI
            # backend gave it an alternative.
            serve_parser.error(
                "one of --extensions-dir or --from-openapi is required "
                "(or an apcore-a2a.openapi.spec in your apcore config)"
            )
        _run_serve(args, openapi)
    else:
        parser.print_help()
        sys.exit(1)


def _parse_headers(raw: list[str] | None) -> dict[str, str] | None:
    """Parse repeated ``--openapi-header KEY:VALUE`` flags.

    These authenticate the **spec fetch** only. They are deliberately not reused
    for proxied calls: a document is often public while the API behind it is not.
    """
    if not raw:
        return None
    headers: dict[str, str] = {}
    for item in raw:
        key, sep, value = item.partition(":")
        if not sep or not key.strip():
            # Never echo the offending value: the whole point of this flag is
            # that it carries a credential, and the commonest way to malform it
            # is to paste the token without its `Key:` prefix. Printing it here
            # would put the secret in terminal scrollback and any CI log.
            print(
                'Error: --openapi-header expects KEY:VALUE (got a value with no ":")',
                file=sys.stderr,
            )
            sys.exit(1)
        headers[key.strip()] = value.strip()
    return headers


def _merge_openapi_settings(args: argparse.Namespace) -> object | None:
    """Resolve the OpenAPI backend settings, CLI flags over Config Bus.

    Returns ``object``, not ``dict``: a wrong-shaped ``apcore-a2a.openapi`` is
    passed through unchanged so the error naming its shape stays reachable, so a
    caller must not assume a mapping.

    Implements the precedence the feature spec states: **an explicit CLI flag
    beats the `apcore-a2a.openapi` Config Bus section, which beats the default.**
    Per key, not per source — a `--openapi-prefix` alongside a config-declared
    `spec` has to take effect, or the flag is a silent no-op.

    Returns ``None`` when neither route names a `spec`, which is the ordinary
    "no OpenAPI configured" outcome rather than an error.
    """
    from apcore_a2a._config import get_a2a_setting

    section: object = get_a2a_setting("openapi")
    if section is not None and not isinstance(section, dict):
        # Do NOT swallow a wrong-shaped section. `openapi: ./spec.json` — the
        # plausible shorthand typo for `openapi: {spec: ./spec.json}` — would
        # otherwise become `{}` here, yield no `spec`, and reach the operator as
        # "one of --extensions-dir or --from-openapi is required": the wrong
        # error, naming neither the key they got wrong nor the shape it wants.
        # `build_openapi_backend_from_config` owns the message that names it;
        # passing the value through is what makes that message reachable.
        return section

    merged: dict[str, object] = dict(section) if isinstance(section, dict) else {}

    # Only overlay a flag the operator actually passed. Every OpenAPI flag
    # defaults to None precisely so that "absent" is distinguishable from
    # "explicitly set to a falsy value" — without that, `--openapi-no-deprecated`
    # left off would silently override a config `include_deprecated: false`.
    overlay: dict[str, object | None] = {
        "spec": args.from_openapi,
        "base_url": args.openapi_base_url,
        "prefix": args.openapi_prefix,
        "include": args.openapi_include,
        "exclude": args.openapi_exclude,
        "headers": _parse_headers(args.openapi_headers),
    }
    if args.openapi_no_deprecated is not None:
        overlay["include_deprecated"] = not args.openapi_no_deprecated
    merged.update({k: v for k, v in overlay.items() if v is not None})

    return merged if merged.get("spec") else None


def _run_serve(args: argparse.Namespace, openapi: object | None = None) -> None:
    """Execute the serve subcommand.

    ``openapi`` is the merged OpenAPI settings from :func:`_merge_openapi_settings`,
    resolved by ``main()`` so the config file is read once. It defaults to ``None``
    only so that a direct call in a test need not supply it.
    """
    from apcore import Registry

    # Step 1: Load the registry from whichever backend source(s) were given.
    # `main()` has already rejected the neither-given case as a usage error.
    registry = None
    if args.extensions_dir:
        extensions_dir = Path(args.extensions_dir).resolve()
        if not extensions_dir.exists():
            print(
                f"Error: Extensions directory not found: {extensions_dir}",
                file=sys.stderr,
            )
            sys.exit(1)
        if not extensions_dir.is_dir():
            print(f"Error: Not a directory: {extensions_dir}", file=sys.stderr)
            sys.exit(1)
        registry = Registry(extensions_dir=str(extensions_dir))

    # `main()` resolved this already; only a direct call needs the fallback.
    if openapi is None:
        openapi = _merge_openapi_settings(args)
    if openapi:
        from apcore_a2a.openapi_backend import build_openapi_backend_from_config

        try:
            registry = build_openapi_backend_from_config(
                openapi,
                registry=registry,
                has_other_backend_source=bool(args.extensions_dir),
            )
        except Exception as exc:  # noqa: BLE001
            # Deliberately broad. `load_spec` raises `httpx.HTTPError` for a URL
            # and `OSError` for a path, neither of which is a ValueError — a
            # narrow clause here turns `--from-openapi ./missing.json` into an
            # unhandled traceback. The toolkit's message names the resolved
            # location and never the headers, so it is safe to print.
            print(f"Error: OpenAPI backend: {exc}", file=sys.stderr)
            sys.exit(1)

    assert registry is not None  # guarded above
    modules = registry.list()
    if not modules:
        # `openapi` is provably a mapping here: a wrong-shaped section is passed
        # through by the merge and rejected by the call above, which exits. The
        # isinstance guard states that for the type checker rather than assuming it.
        spec = openapi.get("spec") if isinstance(openapi, dict) else None
        source = spec or args.extensions_dir
        print(f"Error: No modules discovered in {source}", file=sys.stderr)
        sys.exit(1)
    print(f"Discovered {len(modules)} module(s): {', '.join(modules)}")

    # Step 3: Build auth
    auth = None
    if args.auth_type == "bearer":
        key = _resolve_auth_key(args.auth_key)
        if not key:
            print(
                "Error: --auth-key is required when --auth-type is bearer",
                file=sys.stderr,
            )
            sys.exit(1)
        from apcore_a2a.auth import JWTAuthenticator

        auth = JWTAuthenticator(
            key=key,
            issuer=args.auth_issuer,
            audience=args.auth_audience,
        )

    # Step 4: Resolve URL
    url = args.url or f"http://{args.host}:{args.port}"

    # Warn when binding to all interfaces without auth
    if args.host == "0.0.0.0" and auth is None:
        import logging

        logging.getLogger(__name__).warning(
            "--host 0.0.0.0 binds to all network interfaces without authentication; "
            "consider using --host 127.0.0.1 or enabling --auth-type bearer"
        )

    # Step 5: Call serve()
    from apcore_a2a import serve

    try:
        serve(
            registry,
            host=args.host,
            port=args.port,
            name=args.name,
            description=args.description,
            version=args.agent_version,
            url=url,
            auth=auth,
            push_notifications=args.push_notifications,
            explorer=args.explorer,
            cors_origins=args.cors_origins,
            execution_timeout=args.execution_timeout,
            log_level=args.log_level,
        )
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)


def _resolve_auth_key(auth_key: str | None) -> str | None:
    """Resolve the auth key from a file path, literal value, or env var.

    Priority:
    1. If auth_key is a path to an existing file → read file contents (strip whitespace)
    2. If auth_key is provided but not a file → use as literal key
    3. If auth_key is None → check APCORE_JWT_SECRET env var
    4. Return None if nothing found
    """
    if auth_key:
        p = Path(auth_key)
        if p.exists():
            return p.read_text().strip()
        return auth_key
    return os.environ.get("APCORE_JWT_SECRET")


if __name__ == "__main__":
    main()
