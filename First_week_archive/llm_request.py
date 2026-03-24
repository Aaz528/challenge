#!/usr/bin/env python3
"""Запрос к LLM API: один ввод пользователя и 4 варианта ответа."""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ.get("OPENAI_API_KEY", "")
BASE_URL = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1")
MODEL = os.environ.get("LLM_MODEL", "gpt-3.5-turbo")


def ask_llm(messages: list[dict]) -> str:
    payload = {"model": MODEL, "messages": messages}
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

    base_messages = [{"role": "user", "content": prompt}]

    # 1. Просто ответ
    print("\n--- 1. Просто ответ ---")
    print(ask_llm(base_messages))

    # 2. Добавить условие "решать пошагово"
    print("\n--- 2. Ответ: решать пошагово ---")
    step_by_step_messages = [
        {
            "role": "user",
            "content": f"{prompt}\n\nУсловие: решать пошагово.",
        }
    ]
    print(ask_llm(step_by_step_messages))

    # 3. Сначала составить промт на первоначальный запрос, затем отправить этот промт и получить ответ
    print("\n--- 3. Сгенерировать промт -> ответить по нему ---")
    prompt_builder = (
        "Составь лучший промт (одной строкой или несколькими), чтобы другая LLM максимально качественно "
        "ответила на следующий пользовательский запрос. Верни ТОЛЬКО сам промт, без пояснений.\n\n"
        f"Пользовательский запрос:\n{prompt}"
    )
    improved_prompt = ask_llm([{"role": "user", "content": prompt_builder}])
    print("\n[Промт]\n" + improved_prompt)
    print("\n[Ответ]\n" + ask_llm([{"role": "user", "content": improved_prompt}]))

    # 4. Эксперты (аналитик, инженер, критик) на базе промта из 3-го варианта
    print("\n--- 4. Эксперты: аналитик / инженер / критик ---")
    expert_base = (
        "Ниже промт. Ответь на него в рамках своей роли.\n\n"
        f"{improved_prompt}"
    )
    experts: list[tuple[str, str]] = [
        ("Аналитик", "Ты аналитик. Дай структурированный анализ и обоснования. Если нужны допущения — явно перечисли."),
        ("Инженер", "Ты инженер. Дай практичное решение: шаги, алгоритм, примеры, детали реализации."),
        ("Критик", "Ты критик. Найди слабые места, риски, альтернативы, и как улучшить ответ/решение."),
    ]
    for title, system_msg in experts:
        print(f"\n[{title}]\n" + ask_llm([{"role": "system", "content": system_msg}, {"role": "user", "content": expert_base}]))


if __name__ == "__main__":
    main()
