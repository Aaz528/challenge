"""
MCP-сервер "CRM из JSON" для учебного саппорта.

Инструменты:
- getUser(user_id)
- getTicket(ticket_id)
- findTicketsByUser(user_id, status="")

По умолчанию читает данные из docs/support_users_tickets.json
(можно переопределить через SUPPORT_CRM_JSON).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "Support-CRM",
    instructions="Инструменты CRM для саппорта: пользователи и тикеты из JSON.",
    host="127.0.0.1",
    port=3342,
    streamable_http_path="/mcp",
    json_response=True,
)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _json(obj: dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def _crm_path() -> Path:
    raw = os.environ.get("SUPPORT_CRM_JSON", "docs/support_users_tickets.json").strip()
    p = Path(raw)
    if not p.is_absolute():
        p = (_project_root() / p).resolve()
    return p


def _load() -> dict[str, Any]:
    path = _crm_path()
    if not path.exists():
        raise FileNotFoundError(f"CRM json not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("CRM JSON должен быть объектом")
    users = data.get("users")
    tickets = data.get("tickets")
    if not isinstance(users, list) or not isinstance(tickets, list):
        raise ValueError("CRM JSON ожидает массивы users и tickets")
    return data


@mcp.tool()
def getUser(user_id: str) -> str:
    """Возвращает пользователя по user_id."""
    uid = (user_id or "").strip()
    if not uid:
        return _json({"ok": False, "error": "user_id is required"})
    data = _load()
    for u in data["users"]:
        if isinstance(u, dict) and str(u.get("id", "")).strip() == uid:
            return _json({"ok": True, "user": u})
    return _json({"ok": False, "error": f"user not found: {uid}"})


@mcp.tool()
def getTicket(ticket_id: str) -> str:
    """Возвращает тикет по ticket_id."""
    tid = (ticket_id or "").strip()
    if not tid:
        return _json({"ok": False, "error": "ticket_id is required"})
    data = _load()
    for t in data["tickets"]:
        if isinstance(t, dict) and str(t.get("id", "")).strip() == tid:
            return _json({"ok": True, "ticket": t})
    return _json({"ok": False, "error": f"ticket not found: {tid}"})


@mcp.tool()
def findTicketsByUser(user_id: str, status: str = "") -> str:
    """Возвращает тикеты пользователя, optionally filtered by status."""
    uid = (user_id or "").strip()
    st = (status or "").strip().lower()
    if not uid:
        return _json({"ok": False, "error": "user_id is required"})
    data = _load()
    out: list[dict[str, Any]] = []
    for t in data["tickets"]:
        if not isinstance(t, dict):
            continue
        if str(t.get("user_id", "")).strip() != uid:
            continue
        if st and str(t.get("status", "")).strip().lower() != st:
            continue
        out.append(t)
    return _json({"ok": True, "count": len(out), "tickets": out})


def main() -> None:
    import sys

    transport = (sys.argv[1] if len(sys.argv) > 1 else "stdio").strip().lower()
    if transport in ("http", "streamable-http", "streamable_http"):
        transport = "streamable-http"
    elif transport not in ("stdio", "sse"):
        raise SystemExit("Использование: python -m mcp_servers.support_crm_mcp [stdio|streamable-http]")
    mcp.run(transport=transport)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
