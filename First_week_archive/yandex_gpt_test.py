#!/usr/bin/env python3
"""
Проверка YandexGPT через OpenAI-совместимый клиент (Responses API).

.env:
  YANDEX_CLOUD_FOLDER=b1g...     # ID каталога
  YANDEX_CLOUD_API_KEY=AQVN...   # API-ключ
  YANDEX_CLOUD_MODEL=yandexgpt-5.1/latest
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv()

FOLDER = os.environ.get("YANDEX_CLOUD_FOLDER", "").strip()
API_KEY = os.environ.get("YANDEX_CLOUD_API_KEY", "").strip()
MODEL = os.environ.get("YANDEX_CLOUD_MODEL", "yandexgpt-5.1/latest").strip()

BASE_URL = os.environ.get(
    "YANDEX_CLOUD_BASE_URL", "https://ai.api.cloud.yandex.net/v1"
).rstrip("/")


def main() -> None:
    if not FOLDER or not API_KEY:
        print(
            "Задайте в .env YANDEX_CLOUD_FOLDER и YANDEX_CLOUD_API_KEY",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        from openai import OpenAI
    except ImportError:
        print("Установите пакет: pip install openai", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(
        api_key=API_KEY,
        base_url=BASE_URL,
        project=FOLDER,
    )

    model_uri = f"gpt://{FOLDER}/{MODEL}"
    response = client.responses.create(
        model=model_uri,
        temperature=0.3,
        instructions="Отвечай кратко и по делу.",
        input="Ответь одним предложением: что такое API?",
        max_output_tokens=500,
    )

    # output_text есть у объекта ответа Responses API
    text = getattr(response, "output_text", None) or str(response)
    print("OK, модель:", model_uri)
    print(text)


if __name__ == "__main__":
    main()
