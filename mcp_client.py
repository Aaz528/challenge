"""
Клиент Model Context Protocol на базе официального SDK (`mcp`).

Транспорты: stdio (подпроцесс-сервер) и Streamable HTTP.

Переменные окружения (пример):

  MCP_ENABLED=1
  MCP_TRANSPORT=stdio
  MCP_STDIO_COMMAND=npx
  MCP_STDIO_ARGS='["-y","@modelcontextprotocol/server-filesystem","/tmp"]'

  MCP_TRANSPORT=streamable_http
  # Удалённый MCP (ничего не ставите на свой ПК — только HTTP-клиент):
  MCP_STREAMABLE_HTTP_URL=https://your-host.example/mcp
  MCP_STREAMABLE_HTTP_HEADERS_JSON='{"Authorization":"Bearer <token>"}'

Использование из async-кода:

  from app_settings import load_mcp_settings
  from mcp_client import session_from_settings, list_tools_dicts, call_tool_text

  settings = load_mcp_settings()
  async with session_from_settings(settings) as session:
      tools = await list_tools_dicts(session)
      text, err = await call_tool_text(session, "tool_name", {"arg": "v"})
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from app_settings import MCPServerProfile, MCPSettings, load_mcp_settings


@asynccontextmanager
async def session_stdio(
    command: str,
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
) -> AsyncIterator[ClientSession]:
    params = StdioServerParameters(command=command, args=args, env=env, cwd=cwd)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


@asynccontextmanager
async def session_streamable_http(
    url: str,
    *,
    http_timeout_sec: float = 45.0,
    headers: dict[str, str] | None = None,
) -> AsyncIterator[ClientSession]:
    """
    Удалённый MCP: достаточно URL на другой хост (https://.../mcp). Локально — только httpx.

    Без своего httpx.AsyncClient SDK подставляет read-timeout до ~300s на SSE — при ошибке URL
    кажется «висит»; здесь таймауты ужаты.
    """
    t = max(5.0, float(http_timeout_sec))
    timeout = httpx.Timeout(t, connect=min(10.0, t), read=t, write=min(30.0, t))
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers=headers,
    ) as http_client:
        async with streamable_http_client(url, http_client=http_client) as (
            read,
            write,
            _get_session_id,
        ):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session


@asynccontextmanager
async def session_from_profile(
    profile: MCPServerProfile,
) -> AsyncIterator[ClientSession]:
    """Подключение к одному MCP-серверу по профилю (несколько серверов — несколько профилей)."""
    tr = (profile.transport or "").strip().lower()
    if tr == "stdio":
        if not profile.stdio_command:
            raise ValueError(f"MCP [{profile.id}]: для stdio нужен stdio_command.")
        async with session_stdio(profile.stdio_command, list(profile.stdio_args)) as session:
            yield session
    elif tr in ("streamable_http", "http", "streamable-http"):
        if not profile.streamable_http_url:
            raise ValueError(f"MCP [{profile.id}]: для streamable HTTP нужен streamable_http_url.")
        hdrs = dict(profile.streamable_http_headers) if profile.streamable_http_headers else None
        async with session_streamable_http(
            profile.streamable_http_url,
            http_timeout_sec=profile.http_timeout_sec,
            headers=hdrs,
        ) as session:
            yield session
    else:
        raise ValueError(
            f"MCP [{profile.id}]: transport должен быть stdio | streamable_http, получено {tr!r}."
        )


@asynccontextmanager
async def session_from_settings(
    settings: MCPSettings | None = None,
) -> AsyncIterator[ClientSession]:
    s = settings if settings is not None else load_mcp_settings()
    if not s.enabled:
        raise ValueError("MCP выключен (MCP_ENABLED) или настройки не заданы.")
    p = MCPServerProfile(
        id="default",
        transport=s.transport,
        stdio_command=s.stdio_command,
        stdio_args=s.stdio_args,
        streamable_http_url=s.streamable_http_url,
        http_timeout_sec=s.http_timeout_sec,
        streamable_http_headers=s.streamable_http_headers,
    )
    async with session_from_profile(p) as session:
        yield session


def tool_to_dict(tool: types.Tool) -> dict[str, Any]:
    schema: Any = tool.inputSchema
    if hasattr(schema, "model_dump"):
        schema = schema.model_dump(mode="json")
    elif schema is None:
        schema = {}
    out: dict[str, Any] = {
        "name": tool.name,
        "description": tool.description or "",
        "inputSchema": schema,
    }
    if tool.title:
        out["title"] = tool.title
    return out


async def list_tools_dicts(session: ClientSession) -> list[dict[str, Any]]:
    res = await session.list_tools()
    return [tool_to_dict(t) for t in res.tools]


async def call_tool_text(
    session: ClientSession,
    name: str,
    arguments: dict[str, Any] | None = None,
) -> tuple[str, bool]:
    """
    Вызывает инструмент и собирает текстовые блоки ответа.
    Возвращает (текст, is_error).
    """
    result = await session.call_tool(name, arguments or {})
    parts: list[str] = []
    for block in result.content:
        if isinstance(block, types.TextContent):
            parts.append(block.text)
    return "\n".join(parts), bool(result.isError)


__all__ = [
    "call_tool_text",
    "list_tools_dicts",
    "load_mcp_settings",
    "session_from_profile",
    "session_from_settings",
    "session_stdio",
    "session_streamable_http",
    "tool_to_dict",
]
