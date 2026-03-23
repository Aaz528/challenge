#!/usr/bin/env python3
"""
Один запрос пользователя — по очереди ответы от DeepSeek, GigaChat, Yandex GPT.
После текста каждого ответа: строка с моделью, числом токенов и временем.

.env (как у вас уже настроено):
  DeepSeek:  OPENAI_API_KEY, OPENAI_API_BASE, LLM_MODEL
  GigaChat:  GIGACHAT_*, как в gigachat_test.py
  Yandex:    YANDEX_CLOUD_FOLDER, YANDEX_CLOUD_API_KEY, YANDEX_CLOUD_MODEL
"""

from __future__ import annotations

import os
import sys
import time

import requests
from dotenv import load_dotenv

load_dotenv()

# --- DeepSeek (OpenAI-совместимый) ---
DS_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
DS_BASE = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1").rstrip("/")
DS_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat").strip()

# --- Yandex ---
Y_FOLDER = os.environ.get("YANDEX_CLOUD_FOLDER", "").strip()
Y_KEY = os.environ.get("YANDEX_CLOUD_API_KEY", "").strip()
Y_MODEL = os.environ.get("YANDEX_CLOUD_MODEL", "yandexgpt-5.1/latest").strip()
Y_BASE = os.environ.get(
    "YANDEX_CLOUD_BASE_URL", "https://ai.api.cloud.yandex.net/v1"
).rstrip("/")

GIGA_KEY = os.environ.get("GIGACHAT_AUTHORIZATION_KEY", "").strip()
GIGA_MODEL = os.environ.get("GIGACHAT_MODEL", "GigaChat").strip()


def _usage_total(usage: dict | None) -> int | None:
    if not usage or not isinstance(usage, dict):
        return None
    t = usage.get("total_tokens")
    if t is not None:
        return int(t)
    p = usage.get("prompt_tokens") or 0
    c = usage.get("completion_tokens") or 0
    if p or c:
        return int(p) + int(c)
    return None


def _footer(model_label: str, tokens: int | None, elapsed_sec: float) -> str:
    tok = str(tokens) if tokens is not None else "н/д"
    return f"Модель: {model_label} | токенов: {tok} | время ответа: {elapsed_sec:.2f} с"


def ask_deepseek(user_prompt: str) -> tuple[str, str, int | None, float]:
    t0 = time.perf_counter()
    resp = requests.post(
        f"{DS_BASE}/chat/completions",
        headers={
            "Authorization": f"Bearer {DS_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": DS_MODEL,
            "messages": [{"role": "user", "content": user_prompt}],
        },
        timeout=120,
    )
    elapsed = time.perf_counter() - t0
    resp.raise_for_status()
    data = resp.json()
    text = data["choices"][0]["message"]["content"].strip()
    tokens = _usage_total(data.get("usage"))
    label = f"DeepSeek ({DS_MODEL})"
    return text, label, tokens, elapsed


def ask_gigachat(user_prompt: str) -> tuple[str, str, int | None, float]:
    # Ленивый импорт: подтянет SSL/urllib3 из gigachat_test при необходимости
    from gigachat_test import chat_completion, get_access_token

    t0 = time.perf_counter()
    token = get_access_token()
    r = chat_completion(token, user_prompt)
    elapsed = time.perf_counter() - t0
    if not r.ok:
        print("GigaChat HTTP", r.status_code, file=sys.stderr)
        print(r.text[:2000], file=sys.stderr)
        r.raise_for_status()
    data = r.json()
    text = data["choices"][0]["message"]["content"].strip()
    tokens = _usage_total(data.get("usage"))
    label = f"GigaChat ({GIGA_MODEL})"
    return text, label, tokens, elapsed


def ask_yandex(user_prompt: str) -> tuple[str, str, int | None, float]:
    from openai import OpenAI

    client = OpenAI(api_key=Y_KEY, base_url=Y_BASE, project=Y_FOLDER)
    model_uri = f"gpt://{Y_FOLDER}/{Y_MODEL}"

    t0 = time.perf_counter()
    response = client.responses.create(
        model=model_uri,
        temperature=0.3,
        instructions="Отвечай по существу запроса пользователя.",
        input=user_prompt,
        max_output_tokens=4096,
    )
    elapsed = time.perf_counter() - t0

    text = (getattr(response, "output_text", None) or "").strip() or str(response)

    tokens: int | None = None
    usage = getattr(response, "usage", None)
    if usage is not None:
        tokens = getattr(usage, "total_tokens", None)
        if tokens is None:
            inp = getattr(usage, "input_tokens", None) or 0
            out = getattr(usage, "output_tokens", None) or 0
            if inp or out:
                tokens = int(inp) + int(out)

    label = f"Yandex GPT ({model_uri})"
    return text, label, tokens, elapsed


def print_block(title: str, text: str, footer: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")
    print(text)
    print()
    print(footer)


def main() -> None:
    user_prompt = input("Ваш запрос: ").strip()
    if not user_prompt:
        print("Пустой запрос.")
        sys.exit(1)

    # 1) DeepSeek
    if not DS_KEY:
        print("Пропуск DeepSeek: нет OPENAI_API_KEY в .env", file=sys.stderr)
    else:
        try:
            text, label, tokens, elapsed = ask_deepseek(user_prompt)
            print_block("1. DeepSeek", text, _footer(label, tokens, elapsed))
        except Exception as e:
            print(f"\nDeepSeek: ошибка — {e}", file=sys.stderr)
            if os.environ.get("DEBUG"):
                raise

    # 2) GigaChat
    if not GIGA_KEY:
        print("Пропуск GigaChat: нет GIGACHAT_AUTHORIZATION_KEY в .env", file=sys.stderr)
    else:
        try:
            text, label, tokens, elapsed = ask_gigachat(user_prompt)
            print_block("2. GigaChat", text, _footer(label, tokens, elapsed))
        except Exception as e:
            print(f"\nGigaChat: ошибка — {e}", file=sys.stderr)
            if os.environ.get("DEBUG"):
                raise

    # 3) Yandex
    if not Y_FOLDER or not Y_KEY:
        print(
            "Пропуск Yandex GPT: задайте YANDEX_CLOUD_FOLDER и YANDEX_CLOUD_API_KEY",
            file=sys.stderr,
        )
    else:
        try:
            text, label, tokens, elapsed = ask_yandex(user_prompt)
            print_block("3. Yandex GPT", text, _footer(label, tokens, elapsed))
        except Exception as e:
            print(f"\nYandex GPT: ошибка — {e}", file=sys.stderr)
            if os.environ.get("DEBUG"):
                raise


if __name__ == "__main__":
    main()
