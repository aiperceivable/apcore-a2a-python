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
    serve_parser.add_argument("--extensions-dir", required=True)
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
        _run_serve(args)
    else:
        parser.print_help()
        sys.exit(1)


def _run_serve(args: argparse.Namespace) -> None:
    """Execute the serve subcommand."""
    # Step 1: Validate extensions dir
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

    # Step 2: Load registry
    from apcore import Registry

    registry = Registry(extensions_dir=str(extensions_dir))
    modules = registry.list()
    if not modules:
        print(
            f"Error: No modules discovered in {extensions_dir}",
            file=sys.stderr,
        )
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
