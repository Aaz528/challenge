"""Парсинг настроек MCP без запуска сервера."""

from __future__ import annotations

import pytest

from app_settings import load_mcp_server_profiles, load_mcp_settings


def test_load_mcp_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MCP_ENABLED", raising=False)
    monkeypatch.delenv("MCP_TRANSPORT", raising=False)
    s = load_mcp_settings()
    assert s.enabled is False


def test_load_mcp_stdio_args_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_ENABLED", "1")
    monkeypatch.setenv("MCP_TRANSPORT", "stdio")
    monkeypatch.setenv("MCP_STDIO_COMMAND", "python")
    monkeypatch.setenv("MCP_STDIO_ARGS", '["-c", "pass"]')
    s = load_mcp_settings()
    assert s.enabled is True
    assert s.stdio_command == "python"
    assert s.stdio_args == ("-c", "pass")


def test_load_mcp_server_profiles_legacy_single(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_ENABLED", "1")
    monkeypatch.setenv("MCP_TRANSPORT", "stdio")
    monkeypatch.setenv("MCP_STDIO_COMMAND", "python")
    monkeypatch.setenv("MCP_STDIO_ARGS", '["-c", "pass"]')
    monkeypatch.delenv("MCP_SERVERS_JSON", raising=False)
    profs = load_mcp_server_profiles()
    assert len(profs) == 1
    assert profs[0].id == "default"
    assert profs[0].stdio_command == "python"


def test_load_mcp_server_profiles_json_multi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_ENABLED", "1")
    monkeypatch.setenv(
        "MCP_SERVERS_JSON",
        '[{"id":"a","transport":"stdio","stdio_args":["-m","m1"]},'
        '{"id":"b","transport":"stdio","stdio_command":"python3","stdio_args":["-m","m2"]}]',
    )
    monkeypatch.setenv("MCP_STDIO_COMMAND", "/bin/python")
    profs = load_mcp_server_profiles()
    assert len(profs) == 2
    assert profs[0].id == "a"
    assert profs[0].stdio_command == "/bin/python"
    assert profs[0].stdio_args == ("-m", "m1")
    assert profs[1].id == "b"
    assert profs[1].stdio_command == "python3"
