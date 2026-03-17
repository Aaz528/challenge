#!/usr/bin/env python3
"""Минимальный запрос к LLM API — отправка, получение ответа, вывод в консоль."""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

# Настройки: задайте OPENAI_API_KEY и при необходимости OPENAI_API_BASE (по умолчанию OpenAI)
API_KEY = os.environ.get("OPENAI_API_KEY", "")
BASE_URL = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1")
MODEL = os.environ.get("LLM_MODEL", "gpt-3.5-turbo")

def ask_llm(prompt: str) -> str:
    resp = requests.post(
        f"{BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        json={"model": MODEL, "messages": [{"role": "user", "content": prompt}]},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]

if __name__ == "__main__":
    if not API_KEY:
        print("Задайте OPENAI_API_KEY в окружении.")
        exit(1)
    answer = ask_llm("Скажи коротко: привет!")
    print(answer)
