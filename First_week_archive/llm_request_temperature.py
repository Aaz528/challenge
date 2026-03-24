#!/usr/bin/env python3
"""Сравнение ответов LLM при разных температурах и выбор лучшего."""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ.get("OPENAI_API_KEY", "")
BASE_URL = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1")
MODEL = os.environ.get("LLM_MODEL", "gpt-3.5-turbo")


def ask_llm(prompt: str, temperature: float) -> str:
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }
    resp = requests.post(
        f"{BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def build_conclusion(user_prompt: str, answer_t0: str, answer_t07: str, answer_t12: str) -> str:
    judge_prompt = (
        "Ты оцениваешь 3 ответа на один и тот же запрос пользователя.\n"
        "Критерии: корректность, полезность, ясность, соответствие запросу.\n"
        "Выбери лучший ответ для этого конкретного запроса.\n\n"
        f"Запрос пользователя:\n{user_prompt}\n\n"
        "Ответ A (temperature=0):\n"
        f"{answer_t0}\n\n"
        "Ответ B (temperature=0.7):\n"
        f"{answer_t07}\n\n"
        "Ответ C (temperature=1.2):\n"
        f"{answer_t12}\n\n"
        "Верни результат в формате:\n"
        "Лучший вариант: <A/B/C>\n"
        "Вывод: <2-4 предложения, почему этот вариант лучше для данного запроса>"
    )
    return ask_llm(judge_prompt, temperature=0)


def main():
    if not API_KEY:
        print("Задайте OPENAI_API_KEY в .env")
        return

    prompt = input("Ваш запрос: ").strip()
    if not prompt:
        print("Запрос не может быть пустым.")
        return

    answer_t0 = ask_llm(prompt, temperature=0.0)
    answer_t07 = ask_llm(prompt, temperature=0.7)
    answer_t12 = ask_llm(prompt, temperature=1.2)

    print("\n--- 1) Ответ с температурой 0 ---")
    print(answer_t0)

    print("\n--- 2) Ответ с температурой 0.7 ---")
    print(answer_t07)

    print("\n--- 3) Ответ с температурой 1.2 ---")
    print(answer_t12)

    conclusion = build_conclusion(prompt, answer_t0, answer_t07, answer_t12)
    print("\n--- Вывод: какой ответ лучше ---")
    print(conclusion)


if __name__ == "__main__":
    main()
