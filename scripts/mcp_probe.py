#!/usr/bin/env python3
"""
Проверка MCP: соединение и список инструментов.

Запуск из корня репозитория (где лежит mcp_client.py):

  export MCP_ENABLED=1
  export MCP_TRANSPORT=streamable_http
  export MCP_STREAMABLE_HTTP_URL=http://127.0.0.1:8000/mcp

  .venv/bin/python scripts/mcp_probe.py
  .venv/bin/python scripts/mcp_probe.py --ping-only

Или stdio:

  export MCP_TRANSPORT=stdio
  export MCP_STDIO_COMMAND=npx
  export MCP_STDIO_ARGS='["-y","@modelcontextprotocol/server-filesystem","/tmp"]'

  .venv/bin/python scripts/mcp_probe.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv()


async def _run(*, ping_only: bool) -> int:
    from app_settings import load_mcp_settings
    from mcp_client import list_tools_dicts, session_from_settings

    s = load_mcp_settings()
    print("Настройки:", json.dumps(asdict(s), ensure_ascii=False, indent=2))
    if not s.enabled:
        print("\nВключите MCP: MCP_ENABLED=1 и задайте транспорт.", file=sys.stderr)
        return 1
    try:
        async with session_from_settings(s) as session:
            await session.send_ping()
            print("\n✓ Соединение установлено, ping OK.")
            if ping_only:
                return 0
            tools = await list_tools_dicts(session)
            print(f"\nИнструментов: {len(tools)}")
            print(json.dumps(tools, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"\n✗ Ошибка: {e}", file=sys.stderr)
        return 2
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="Проверка MCP-клиента")
    p.add_argument(
        "--ping-only",
        action="store_true",
        help="только ping, без списка инструментов",
    )
    args = p.parse_args()
    code = asyncio.run(_run(ping_only=args.ping_only))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
