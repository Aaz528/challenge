#!/usr/bin/env python3
"""Запрос к LLM API: произвольный запрос пользователя и 4 варианта ответа."""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ.get("OPENAI_API_KEY", "")
BASE_URL = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1")
MODEL = os.environ.get("LLM_MODEL", "gpt-3.5-turbo")


def ask_llm(messages: list[dict], stop: list[str] | None = None) -> str:
    payload = {"model": MODEL, "messages": messages}
    if stop:
        payload["stop"] = stop
    resp = requests.post(
        f"{BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def main():
    if not API_KEY:
        print("Задайте OPENAI_API_KEY в .env")
        return

    prompt = input("Ваш запрос: ").strip()
    if not prompt:
        print("Запрос не может быть пустым.")
        return

    messages = [{"role": "user", "content": prompt}]

    # 1. Просто ответ
    print("\n--- 1. Просто ответ ---")
    print(ask_llm(messages))

    # 2. Сначала описание формата, затем ответ в этом формате
    print("\n--- 2. Ответ с явным форматом ---")
    format_prompt = (
        f"Запрос: {prompt}\n\n"
        "Опиши явно формат ответа (структура, стиль, объём), в котором нужно ответить. "
        "Дай только описание формата, без самого ответа."
    )
    format_desc = ask_llm([{"role": "user", "content": format_prompt}])
    answer_with_format_prompt = (
        f"Запрос: {prompt}\n\n"
        f"Формат ответа:\n{format_desc}\n\n"
        "Дай ответ строго по этому формату."
    )
    print(ask_llm([{"role": "user", "content": answer_with_format_prompt}]))

    # 3. Ограничение длины
    length_hint = input("\nОграничение длины (например: в одном предложении, до 50 слов; Enter = по умолчанию): ").strip()
    if not length_hint:
        length_hint = "не более двух предложений"
    print("\n--- 3. Ответ с ограничением длины ---")
    length_prompt = f"{prompt}\n\nОграничение: {length_hint}."
    print(ask_llm([{"role": "user", "content": length_prompt}]))

    # 4. Stop sequence
    stop_input = input("\nStop sequence (например \\n\\n или ---; Enter = по умолчанию): ").strip()
    if not stop_input:
        stop_seq = "\n\n"
    else:
        stop_seq = stop_input.replace("\\n", "\n").replace("\\t", "\t")
    print("\n--- 4. Ответ с условием завершения (stop) ---")
    print(ask_llm(messages, stop=[stop_seq]))


if __name__ == "__main__":
    main()
