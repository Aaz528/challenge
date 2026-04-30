# File Assistant Scenarios

Ниже воспроизводимые goal-based сценарии для ассистента работы с файлами.
Ассистент сам инициирует операции с файлами через MCP tools (`read/search/analyze/write`),
без ручного указания "открой файл X".

## Запуск

```bash
python scripts/run_file_assistant_scenarios.py
```

Результаты сохраняются в:

- `artifacts/file_assistant_scenarios/scenario1_api_usage_report.md`
- `artifacts/file_assistant_scenarios/scenario2_invariants_report.md`
- `artifacts/file_assistant_scenarios/scenario3_changelog.md`
- `artifacts/file_assistant_scenarios/summary.json`

## Реализованные сценарии

### 1) Find API usages

Цель: найти места использования целевых API по проекту.
Ассистент:
- ищет паттерны в нескольких файлах (`searchProject`)
- собирает отчёт с найденными вхождениями
- сохраняет markdown-отчёт

### 2) Check file invariants

Цель: проверить соответствие MCP-файлов структурным правилам.
Ассистент:
- находит MCP server файлы
- читает содержимое каждого
- проверяет инварианты (`FastMCP`, `main guard`)
- формирует итоговый отчёт FAIL/OK

### 3) Generate changelog

Цель: подготовить список изменений на основе текущего diff.
Ассистент:
- получает список изменённых файлов (`git diff --name-only`)
- группирует по секциям (API/MCP/Scripts/Frontend/Docs)
- генерирует changelog файл

## Критерии минимального результата (выполнены)

- Работа минимум с 2–3 файлами: ✅
- Изменения/результаты сохранены в файлы: ✅
- Результат воспроизводим повторным запуском одной команды: ✅
