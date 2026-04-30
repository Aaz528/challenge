# Карта использования `/api/support/ask`

## 1. Определение эндпоинта (backend)

**Файл:** `api/main.py:1052`
```python
@app.post("/api/support/ask")
async def support_ask(body: SupportAskBody) -> dict[str, Any]:
    """Мини-сервис саппорта: вопрос + контекст тикета/пользователя через MCP + RAG-ответ по docs/code."""
```
- **Роль:** единственное место, где API определяется и обрабатывается
- **Логика:** принимает вопрос, загружает MCP-профили, вызывает supportcrm-инструменты, формирует RAG-ответ

---

## 2. Вызов из фронтенда

**Файл:** `frontend/src/api.ts:245`
```typescript
await fetch("/api/support/ask", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
```
- **Роль:** клиентский вызов API из TypeScript-клиента

---

## 3. Упоминание в тестовом сценарии

**Файл:** `scripts/run_file_assistant_scenarios.py:54`
```python
patterns = [
    r"/api/support/ask",
    r"/api/mcp/file-assistant-demo",
    r"/api/mcp/project-git-demo",
]
```
- **Роль:** скрипт для автоматического поиска всех мест использования API и генерации отчёта

---

## 4. Артефакт-отчёт (сгенерированный ранее)

**Файл:** `artifacts/file_assistant_scenarios/scenario1_api_usage_report.md`
- Содержит ранее сгенерированный отчёт с упоминанием `/api/support/ask` в трёх файлах:
  - `scripts/run_file_assistant_scenarios.py:54`
  - `frontend/src/api.ts:245`
  - `api/main.py:1052`

---

## 5. Внутренние данные (не код)

**Файл:** `chats.db` — бинарная БД чатов, содержит `/api/support/ask` в сохранённых сообщениях (история диалогов)
**Файл:** `rag_index.db` — индекс RAG, содержит строку `@app.post("/api/support/ask")` в проиндексированных документах

---

## Сводка

| # | Файл | Строка | Тип использования |
|---|---|---|---|
| 1 | `api/main.py` | 1052 | **Определение эндпоинта** (backend) |
| 2 | `frontend/src/api.ts` | 245 | **Вызов API** (frontend) |
| 3 | `scripts/run_file_assistant_scenarios.py` | 54 | **Поиск/тестирование** (скрипт) |
| 4 | `artifacts/.../scenario1_api_usage_report.md` | 3,5-7 | **Отчёт** (артефакт) |
| 5 | `chats.db` | — | **Данные** (история чатов) |
| 6 | `rag_index.db` | 19341,23205,24112 | **Индекс** (RAG) |
