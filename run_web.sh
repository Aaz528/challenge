#!/usr/bin/env bash
# Запуск веб-интерфейса: FastAPI (порт 8000) + Vite dev (порт 5173).
# Из корня проекта: ./run_web.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

API_HOST="${API_HOST:-127.0.0.1}"
API_PORT="${API_PORT:-8000}"

if [[ ! -x .venv/bin/uvicorn ]]; then
  echo "Ошибка: нет .venv/bin/uvicorn. Создайте окружение и установите зависимости:"
  echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "Ошибка: не найден npm (нужен для фронтенда)."
  exit 1
fi

if [[ ! -d frontend/node_modules ]]; then
  echo "Устанавливаю зависимости frontend (npm install)..."
  (cd frontend && npm install)
fi

cleanup() {
  if [[ -n "${UVICORN_PID:-}" ]] && kill -0 "$UVICORN_PID" 2>/dev/null; then
    kill "$UVICORN_PID" 2>/dev/null || true
    wait "$UVICORN_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

echo "Запуск API: http://${API_HOST}:${API_PORT}  (документация: /docs)"
.venv/bin/uvicorn api.main:app --host "$API_HOST" --port "$API_PORT" &
UVICORN_PID=$!

sleep 1
echo "Запуск UI (Vite): http://127.0.0.1:5173"
echo "Остановка: Ctrl+C"
(cd frontend && npm run dev)
