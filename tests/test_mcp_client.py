"""Парсинг настроек MCP без запуска сервера."""

from __future__ import annotations

import pytest

from app_settings import load_mcp_settings


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
