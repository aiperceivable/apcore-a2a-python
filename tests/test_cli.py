"""Tests for CLI module (F-09): main(), _run_serve(), _resolve_auth_key()."""

from __future__ import annotations

from argparse import Namespace
from unittest.mock import MagicMock, patch

import pytest

from apcore_a2a.__main__ import _resolve_auth_key, _run_serve, main

# ---------------------------------------------------------------------------
# main() — top-level tests
# ---------------------------------------------------------------------------


def test_main_no_command_exits_1(monkeypatch):
    """main() with no args → sys.exit(1)."""
    monkeypatch.setattr("sys.argv", ["apcore-a2a"])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1


def test_main_version(monkeypatch, capsys):
    """main(["--version"]) → SystemExit(0) with version string printed."""
    monkeypatch.setattr("sys.argv", ["apcore-a2a", "--version"])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    # argparse prints version to stdout
    assert "apcore-a2a" in captured.out or "0.1.0" in captured.out


def test_serve_missing_extensions_dir_exits_2(monkeypatch):
    """--extensions-dir not provided → argparse required-arg error (exit 2)."""
    monkeypatch.setattr("sys.argv", ["apcore-a2a", "serve"])
    with pytest.raises(SystemExit) as exc_info:
        main()
    # argparse exits with code 2 for missing required arguments
    assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# _run_serve() — directory validation
# ---------------------------------------------------------------------------


def test_serve_nonexistent_dir_exits_1(monkeypatch, tmp_path, capsys):
    """--extensions-dir /nonexistent → exit 1, stderr message."""
    nonexistent = str(tmp_path / "nonexistent")
    monkeypatch.setattr("sys.argv", ["apcore-a2a", "serve", "--extensions-dir", nonexistent])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "not found" in captured.err.lower() or "Error" in captured.err


def test_serve_not_a_dir_exits_1(monkeypatch, tmp_path, capsys):
    """--extensions-dir pointing to a file → exit 1, stderr message."""
    some_file = tmp_path / "some_file.txt"
    some_file.write_text("not a directory")
    monkeypatch.setattr("sys.argv", ["apcore-a2a", "serve", "--extensions-dir", str(some_file)])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "not a directory" in captured.err.lower() or "Error" in captured.err


def test_serve_zero_modules_exits_1(tmp_path, capsys):
    """dir exists but registry.list() returns [] → exit 1."""
    ext_dir = tmp_path / "extensions"
    ext_dir.mkdir()

    args = Namespace(
        extensions_dir=str(ext_dir),
        host="0.0.0.0",
        port=8000,
        name=None,
        description=None,
        agent_version=None,
        url=None,
        auth_type=None,
        auth_key=None,
        auth_issuer=None,
        auth_audience=None,
        push_notifications=False,
        explorer=False,
        cors_origins=None,
        execution_timeout=300,
        log_level="info",
    )

    with patch("apcore.Registry") as mock_registry_cls:
        mock_reg = MagicMock()
        mock_reg.list.return_value = []
        mock_registry_cls.return_value = mock_reg

        with pytest.raises(SystemExit) as exc_info:
            _run_serve(args)
        assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "No modules" in captured.err


# ---------------------------------------------------------------------------
# _run_serve() — auth validation
# ---------------------------------------------------------------------------


def test_serve_auth_bearer_missing_key_exits_1(tmp_path, capsys, monkeypatch):
    """--auth-type bearer without --auth-key and no APCORE_JWT_SECRET → exit 1."""
    ext_dir = tmp_path / "extensions"
    ext_dir.mkdir()

    # Make sure APCORE_JWT_SECRET is not set
    monkeypatch.delenv("APCORE_JWT_SECRET", raising=False)

    args = Namespace(
        extensions_dir=str(ext_dir),
        host="0.0.0.0",
        port=8000,
        name=None,
        description=None,
        agent_version=None,
        url=None,
        auth_type="bearer",
        auth_key=None,
        auth_issuer=None,
        auth_audience=None,
        push_notifications=False,
        explorer=False,
        cors_origins=None,
        execution_timeout=300,
        log_level="info",
    )

    with patch("apcore.Registry") as mock_registry_cls:
        mock_reg = MagicMock()
        mock_reg.list.return_value = ["my.module"]
        mock_registry_cls.return_value = mock_reg

        with pytest.raises(SystemExit) as exc_info:
            _run_serve(args)
        assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "auth-key" in captured.err.lower() or "auth_key" in captured.err.lower() or "Error" in captured.err


def test_serve_auth_bearer_with_key(tmp_path, monkeypatch):
    """--auth-type bearer --auth-key mykey → passes (mock serve)."""
    ext_dir = tmp_path / "extensions"
    ext_dir.mkdir()

    args = Namespace(
        extensions_dir=str(ext_dir),
        host="0.0.0.0",
        port=8000,
        name=None,
        description=None,
        agent_version=None,
        url=None,
        auth_type="bearer",
        auth_key="mykey",
        auth_issuer=None,
        auth_audience=None,
        push_notifications=False,
        explorer=False,
        cors_origins=None,
        execution_timeout=300,
        log_level="info",
    )

    with patch("apcore.Registry") as mock_registry_cls, patch("apcore_a2a.serve") as mock_serve:
        mock_reg = MagicMock()
        mock_reg.list.return_value = ["my.module"]
        mock_registry_cls.return_value = mock_reg

        _run_serve(args)

    mock_serve.assert_called_once()


def test_serve_auth_bearer_with_jwt_secret_env(tmp_path, monkeypatch, capsys):
    """APCORE_JWT_SECRET env var used as fallback when --auth-key not provided."""
    ext_dir = tmp_path / "extensions"
    ext_dir.mkdir()

    monkeypatch.setenv("APCORE_JWT_SECRET", "env_secret_key")

    args = Namespace(
        extensions_dir=str(ext_dir),
        host="0.0.0.0",
        port=8000,
        name=None,
        description=None,
        agent_version=None,
        url=None,
        auth_type="bearer",
        auth_key=None,
        auth_issuer=None,
        auth_audience=None,
        push_notifications=False,
        explorer=False,
        cors_origins=None,
        execution_timeout=300,
        log_level="info",
    )

    with patch("apcore.Registry") as mock_registry_cls, patch("apcore_a2a.serve") as mock_serve:
        mock_reg = MagicMock()
        mock_reg.list.return_value = ["my.module"]
        mock_registry_cls.return_value = mock_reg

        _run_serve(args)

    mock_serve.assert_called_once()


# ---------------------------------------------------------------------------
# _run_serve() — runtime error handling
# ---------------------------------------------------------------------------


def test_serve_runtime_error_exits_2(tmp_path, capsys):
    """serve() raises RuntimeError → exit 2."""
    ext_dir = tmp_path / "extensions"
    ext_dir.mkdir()

    args = Namespace(
        extensions_dir=str(ext_dir),
        host="0.0.0.0",
        port=8000,
        name=None,
        description=None,
        agent_version=None,
        url=None,
        auth_type=None,
        auth_key=None,
        auth_issuer=None,
        auth_audience=None,
        push_notifications=False,
        explorer=False,
        cors_origins=None,
        execution_timeout=300,
        log_level="info",
    )

    with patch("apcore.Registry") as mock_registry_cls, patch("apcore_a2a.serve") as mock_serve:
        mock_reg = MagicMock()
        mock_reg.list.return_value = ["my.module"]
        mock_registry_cls.return_value = mock_reg
        mock_serve.side_effect = RuntimeError("something went wrong")

        with pytest.raises(SystemExit) as exc_info:
            _run_serve(args)
        assert exc_info.value.code == 2

    captured = capsys.readouterr()
    assert "Error" in captured.err or "something went wrong" in captured.err


def test_serve_keyboard_interrupt_exits_0(tmp_path):
    """serve() raises KeyboardInterrupt → exit 0."""
    ext_dir = tmp_path / "extensions"
    ext_dir.mkdir()

    args = Namespace(
        extensions_dir=str(ext_dir),
        host="0.0.0.0",
        port=8000,
        name=None,
        description=None,
        agent_version=None,
        url=None,
        auth_type=None,
        auth_key=None,
        auth_issuer=None,
        auth_audience=None,
        push_notifications=False,
        explorer=False,
        cors_origins=None,
        execution_timeout=300,
        log_level="info",
    )

    with patch("apcore.Registry") as mock_registry_cls, patch("apcore_a2a.serve") as mock_serve:
        mock_reg = MagicMock()
        mock_reg.list.return_value = ["my.module"]
        mock_registry_cls.return_value = mock_reg
        mock_serve.side_effect = KeyboardInterrupt()

        with pytest.raises(SystemExit) as exc_info:
            _run_serve(args)
        assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# _run_serve() — argument forwarding
# ---------------------------------------------------------------------------


def test_serve_calls_serve_with_correct_args(tmp_path):
    """mock serve(), verify called with right args."""
    ext_dir = tmp_path / "extensions"
    ext_dir.mkdir()

    args = Namespace(
        extensions_dir=str(ext_dir),
        host="127.0.0.1",
        port=9090,
        name="MyAgent",
        description="A test agent",
        agent_version="1.2.3",
        url="http://myagent.example.com",
        auth_type=None,
        auth_key=None,
        auth_issuer=None,
        auth_audience=None,
        push_notifications=True,
        explorer=True,
        cors_origins=["https://example.com"],
        execution_timeout=600,
        log_level="debug",
    )

    with patch("apcore.Registry") as mock_registry_cls, patch("apcore_a2a.serve") as mock_serve:
        mock_reg = MagicMock()
        mock_reg.list.return_value = ["my.module", "other.module"]
        mock_registry_cls.return_value = mock_reg

        _run_serve(args)

    mock_serve.assert_called_once()
    call_kwargs = mock_serve.call_args

    # Positional arg: registry
    assert call_kwargs.args[0] is mock_reg

    # Keyword args
    assert call_kwargs.kwargs["host"] == "127.0.0.1"
    assert call_kwargs.kwargs["port"] == 9090
    assert call_kwargs.kwargs["name"] == "MyAgent"
    assert call_kwargs.kwargs["description"] == "A test agent"
    assert call_kwargs.kwargs["version"] == "1.2.3"
    assert call_kwargs.kwargs["url"] == "http://myagent.example.com"
    assert call_kwargs.kwargs["auth"] is None
    assert call_kwargs.kwargs["push_notifications"] is True
    assert call_kwargs.kwargs["explorer"] is True
    assert call_kwargs.kwargs["cors_origins"] == ["https://example.com"]
    assert call_kwargs.kwargs["execution_timeout"] == 600
    assert call_kwargs.kwargs["log_level"] == "debug"


def test_serve_default_url_constructed_from_host_port(tmp_path):
    """When --url is not provided, url defaults to http://{host}:{port}."""
    ext_dir = tmp_path / "extensions"
    ext_dir.mkdir()

    args = Namespace(
        extensions_dir=str(ext_dir),
        host="192.168.1.100",
        port=7777,
        name=None,
        description=None,
        agent_version=None,
        url=None,  # No URL provided
        auth_type=None,
        auth_key=None,
        auth_issuer=None,
        auth_audience=None,
        push_notifications=False,
        explorer=False,
        cors_origins=None,
        execution_timeout=300,
        log_level="info",
    )

    with patch("apcore.Registry") as mock_registry_cls, patch("apcore_a2a.serve") as mock_serve:
        mock_reg = MagicMock()
        mock_reg.list.return_value = ["my.module"]
        mock_registry_cls.return_value = mock_reg

        _run_serve(args)

    call_kwargs = mock_serve.call_args
    assert call_kwargs.kwargs["url"] == "http://192.168.1.100:7777"


# ---------------------------------------------------------------------------
# _resolve_auth_key() — unit tests
# ---------------------------------------------------------------------------


def test_resolve_auth_key_literal():
    """Literal key string → returns the string as-is."""
    result = _resolve_auth_key("mysecretkey")
    assert result == "mysecretkey"


def test_resolve_auth_key_file(tmp_path):
    """Path to an existing file → returns file contents (stripped)."""
    key_file = tmp_path / "secret.key"
    key_file.write_text("  file_secret_value  \n")
    result = _resolve_auth_key(str(key_file))
    assert result == "file_secret_value"


def test_resolve_auth_key_env_fallback(monkeypatch):
    """auth_key=None, APCORE_JWT_SECRET env var set → returns env var value."""
    monkeypatch.setenv("APCORE_JWT_SECRET", "env_secret")
    result = _resolve_auth_key(None)
    assert result == "env_secret"


def test_resolve_auth_key_none(monkeypatch):
    """auth_key=None, no APCORE_JWT_SECRET → returns None."""
    monkeypatch.delenv("APCORE_JWT_SECRET", raising=False)
    result = _resolve_auth_key(None)
    assert result is None
