#!/usr/bin/env python3
"""
Проверка GigaChat API: OAuth → access token → короткий запрос в chat/completions.

.env:
  GIGACHAT_AUTHORIZATION_KEY, GIGACHAT_SCOPE, GIGACHAT_OAUTH_URL
  GIGACHAT_API_BASE, GIGACHAT_MODEL — опционально

SSL (часто нужно на Linux из‑за цепочки Сбера / НУЦ Минцифры):
  GIGACHAT_CA_BUNDLE=/абсолютный/путь/к/russian_trusted_root_ca_pem.crt.pem
  (скачать «Корневые сертификаты Минцифры РФ» с https://gu-st.ru/ и указать .pem)

  Только для отладки (небезопасно): GIGACHAT_SSL_VERIFY=0
"""

from __future__ import annotations

import json
import os
import sys
import uuid

import requests
from dotenv import load_dotenv

load_dotenv()

AUTH_KEY = os.environ.get("GIGACHAT_AUTHORIZATION_KEY", "").strip()
SCOPE = os.environ.get("GIGACHAT_SCOPE", "GIGACHAT_API_PERS").strip()
OAUTH_URL = os.environ.get(
    "GIGACHAT_OAUTH_URL", "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
).strip()
API_BASE = os.environ.get(
    "GIGACHAT_API_BASE", "https://gigachat.devices.sberbank.ru/api/v1"
).rstrip("/")
MODEL = os.environ.get("GIGACHAT_MODEL", "GigaChat").strip()


def _ssl_verify():
    """Путь к CA bundle, True (системные CA) или False (только отладка)."""
    flag = os.environ.get("GIGACHAT_SSL_VERIFY", "1").strip().lower()
    if flag in ("0", "false", "no", "off"):
        print(
            "ВНИМАНИЕ: проверка SSL отключена (GIGACHAT_SSL_VERIFY=0). "
            "Только для локальной отладки.",
            file=sys.stderr,
        )
        return False
    bundle = os.environ.get("GIGACHAT_CA_BUNDLE", "").strip()
    if bundle:
        if not os.path.isfile(bundle):
            raise SystemExit(f"GIGACHAT_CA_BUNDLE: файл не найден: {bundle}")
        return bundle
    return True


SSL_VERIFY = _ssl_verify()

if SSL_VERIFY is False:
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _authorization_header() -> str:
    if not AUTH_KEY:
        raise SystemExit("В .env нет GIGACHAT_AUTHORIZATION_KEY")
    if AUTH_KEY.lower().startswith("basic "):
        return AUTH_KEY
    return f"Basic {AUTH_KEY}"


def get_access_token() -> str:
    rq_uid = str(uuid.uuid4())
    resp = requests.post(
        OAUTH_URL,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "RqUID": rq_uid,
            "Authorization": _authorization_header(),
        },
        data={"scope": SCOPE},
        timeout=60,
        verify=SSL_VERIFY,
    )
    if not resp.ok:
        print("OAuth HTTP", resp.status_code, file=sys.stderr)
        print(resp.text[:2000], file=sys.stderr)
        resp.raise_for_status()
    data = resp.json()
    token = data.get("access_token")
    if not token:
        print("Неожиданный ответ OAuth:", json.dumps(data, ensure_ascii=False)[:2000])
        raise SystemExit(1)
    return token


def chat_completion(access_token: str, user_message: str) -> requests.Response:
    rq_uid = str(uuid.uuid4())
    return requests.post(
        f"{API_BASE}/chat/completions",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "RqUID": rq_uid,
        },
        json={
            "model": MODEL,
            "messages": [{"role": "user", "content": user_message}],
        },
        timeout=120,
        verify=SSL_VERIFY,
    )


def main() -> None:
    print("1) Запрос access token…")
    try:
        token = get_access_token()
    except requests.exceptions.SSLError as e:
        print(
            "SSL: проверка сертификата не прошла.\n"
            "  • Укажите в .env путь к корневому PEM Минцифры, например:\n"
            "    GIGACHAT_CA_BUNDLE=/полный/путь/russian_trusted_root_ca_pem.crt.pem\n"
            "    (архив с PEM: https://gu-st.ru/ — раздел про доверенные корневые сертификаты)\n"
            "  • Либо временно для отладки: GIGACHAT_SSL_VERIFY=0 (небезопасно).",
            file=sys.stderr,
        )
        raise e
    print("   OK, токен получен (длина:", len(token), "символов)")

    msg = "Ответь одним коротким предложением: что такое OAuth2?"
    print("2) Запрос chat/completions…")
    r = chat_completion(token, msg)
    if not r.ok:
        print("Chat HTTP", r.status_code, file=sys.stderr)
        print(r.text[:2000], file=sys.stderr)
        r.raise_for_status()

    body = r.json()
    try:
        answer = body["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError):
        print("Неожиданный ответ chat:", json.dumps(body, ensure_ascii=False)[:3000])
        raise SystemExit(1)

    print("   Ответ модели:\n")
    print(answer)


if __name__ == "__main__":
    main()
