#!/usr/bin/env python3
"""
Проверка OpenRouter.

.env:
  OPENROUTER_API_KEY, OPENROUTER_API_BASE (по умолчанию https://openrouter.ai/api/v1),
  OPENROUTER_MODEL

Режим проверки (модель должна соответствовать эндпоинту):
  OPENROUTER_TEST_MODE=chat        — POST /chat/completions (по умолчанию)
  OPENROUTER_TEST_MODE=embeddings — POST /embeddings (для embedding-моделей)

Имена переменных должны начинаться с OPENROUTER_ (не OUTER_).
Поддерживаются опечатки OUTER_MODEL / OUTER_TEST_MODE как запасной вариант с предупреждением в консоль.
"""

from __future__ import annotations

import json
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()


def _env(primary: str, typo_alias: str | None = None) -> str:
    v = os.environ.get(primary, "").strip()
    if v:
        return v
    if typo_alias:
        v2 = os.environ.get(typo_alias, "").strip()
        if v2:
            print(
                f"Подсказка: в .env задано {typo_alias!r} — сработало, "
                f"но переименуйте в {primary!r}.",
                file=sys.stderr,
            )
            return v2
    return ""


API_KEY = _env("OPENROUTER_API_KEY", "OUTER_API_KEY")
BASE = _env("OPENROUTER_API_BASE", "OUTER_API_BASE") or "https://openrouter.ai/api/v1"
BASE = BASE.rstrip("/")
MODEL = _env("OPENROUTER_MODEL", "OUTER_MODEL")
MODE = (_env("OPENROUTER_TEST_MODE", "OUTER_TEST_MODE") or "chat").strip().lower()
REFERRER = os.environ.get("OPENROUTER_HTTP_REFERER", "").strip()
TITLE = os.environ.get("OPENROUTER_APP_TITLE", "challenge-test").strip()


def _headers() -> dict[str, str]:
    h = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    if REFERRER:
        h["HTTP-Referer"] = REFERRER
    if TITLE:
        h["X-Title"] = TITLE
    return h


def _print_openrouter_error(resp: requests.Response) -> None:
    print("HTTP", resp.status_code, file=sys.stderr)
    print(resp.text[:2000], file=sys.stderr)
    try:
        err = resp.json().get("error", {})
        msg = (err.get("message") or "").lower()
        if "embedding model" in msg and "chat" in msg:
            print(
                "\nПодсказка: в OPENROUTER_MODEL указана embedding-модель.\n"
                "  • Либо задайте в .env: OPENROUTER_TEST_MODE=embeddings\n"
                "  • Либо смените OPENROUTER_MODEL на чат-модель (например meta-llama/...).",
                file=sys.stderr,
            )
        if resp.status_code == 402 or "insufficient credits" in msg:
            print(
                "\n402: на аккаунте OpenRouter нет доступных кредитов (или ключ от другого аккаунта).\n"
                "  Даже для «free» моделей часто нужно пополнить баланс в настройках:\n"
                "  https://openrouter.ai/settings/credits",
                file=sys.stderr,
            )
    except (ValueError, TypeError, AttributeError):
        pass


def test_chat() -> None:
    resp = requests.post(
        f"{BASE}/chat/completions",
        headers=_headers(),
        json={
            "model": MODEL,
            "messages": [
                {"role": "user", "content": "Ответь одним коротким предложением: 2+2=?"},
            ],
            "max_tokens": 100,
        },
        timeout=120,
    )
    if not resp.ok:
        _print_openrouter_error(resp)
        resp.raise_for_status()
    data = resp.json()
    text = data["choices"][0]["message"]["content"].strip()
    print("OK (chat), модель:", MODEL)
    print("Ответ:", text)


def test_embeddings() -> None:
    resp = requests.post(
        f"{BASE}/embeddings",
        headers=_headers(),
        json={
            "model": MODEL,
            "input": "Проверка OpenRouter embeddings.",
        },
        timeout=120,
    )
    if not resp.ok:
        _print_openrouter_error(resp)
        resp.raise_for_status()
    data = resp.json()
    vec = data["data"][0]["embedding"]
    preview = vec[:5]
    print("OK (embeddings), модель:", MODEL)
    print("Размерность вектора:", len(vec))
    print("Первые 5 значений:", json.dumps(preview))


def main() -> None:
    if not API_KEY:
        print("Задайте OPENROUTER_API_KEY в .env", file=sys.stderr)
        sys.exit(1)
    if not MODEL:
        print("Задайте OPENROUTER_MODEL в .env", file=sys.stderr)
        sys.exit(1)

    if MODE in ("embed", "embedding", "embeddings"):
        test_embeddings()
    elif MODE == "chat":
        test_chat()
    else:
        print(
            f"Неизвестный OPENROUTER_TEST_MODE={MODE!r}. Используйте chat или embeddings.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
