# PR Review (Assistant + RAG)

- Range: `HEAD~1...HEAD`
- Changed files: **7**

## Потенциальные баги

Потенциальные баги: 1) В `_run_rag_help` нет проверки, что `rag_qa.py` существует — если скрипт отсутствует, `subprocess.run` вызовет `FileNotFoundError`. 2) В `_handle_help_command` не обрабатывается случай, когда `storage.append_message` или `storage.get_branch` выбрасывает исключение (например, при повреждении БД). 3) В `mcp_project_git_demo` нет проверки, что `session_from_profile` успешно создаёт сессию — если профиль некорректен, может быть необработанное исключение. 4) В `project_git_mcp.py` `_run_git` не обрабатывает `TimeoutExpired` — при зависании git-команды вызов упадёт с `subprocess.TimeoutExpired`.

## Архитектурные проблемы

Архитектурные проблемы: дублирование кода между mcp_edu_pipeline и mcp_project_git_demo, смешивание бизнес-логики с HTTP-слоем, неиспользуемый импорт subprocess в chat_service.py, отсутствие обработки ошибок при запуске подпроцесса в _run_rag_help, неявное изменение глобального состояния через _mcp_tool_specs_cache, потенциальная утечка ресурсов при отсутствии async with, отсутствие тестов для нового функционала.

## Рекомендации

Критических проблем нет, но есть рекомендации: 1) В `api/main.py` дублируется логика поиска профиля MCP-сервера — стоит вынести в общую функцию. 2) В `chat_service.py` вызов `subprocess.run` для `/help` блокирует event loop — нужно использовать `asyncio.create_subprocess_exec`. 3) В `mcp_servers/project_git_mcp.py` нет обработки случая, когда `git` не установлен или репозиторий отсутствует. 4) В `scripts/rag_index_lib.py` добавление файлов из `api/*.json` может привести к индексации больших артефактов — стоит ограничить размер или расширения.

## Источники (RAG)

### Баги
- `/home/nout/projects/challenge/api/main.py` | `def mcp_config() -> MCPConfigOut` | chunk_id=`main.py::structured::0051`
- `/home/nout/projects/challenge/api/main.py` | `def mcp_config() -> MCPConfigOut` | chunk_id=`main.py::structured::0052`
- `/home/nout/projects/challenge/chat_service.py` | `def _get_mcp_tool_specs_for_agent() -> list[ToolCallSpec]` | chunk_id=`chat_service.py::structured::0030`
- `/home/nout/projects/challenge/llm_agent.py` | `def _parse_json_object(text` | chunk_id=`llm_agent.py::structured::0031`
- `/home/nout/projects/challenge/docs/rag_antihallucination_report.md` | `heading:q02` | chunk_id=`rag_antihallucination_report.md::structured::0007`
- `/home/nout/projects/challenge/docs/rag_antihallucination_report.md` | `heading:q01` | chunk_id=`rag_antihallucination_report.md::structured::0002`
- `/home/nout/projects/challenge/docs/rag_rerank_comparison.md` | `heading:q01: Где в проекте выполняется маршрутизация вызовов MCP-инструментов по serverid__tool?` | chunk_id=`rag_rerank_comparison.md::structured::0004`
- `/home/nout/projects/challenge/docs/rag_rerank_comparison.md` | `heading:q02: Как устроена поддержка нескольких MCP серверов через MCP_SERVERS_JSON?` | chunk_id=`rag_rerank_comparison.md::structured::0011`

### Архитектура
- `/home/nout/projects/challenge/api/main.py` | `def mcp_config() -> MCPConfigOut` | chunk_id=`main.py::structured::0051`
- `/home/nout/projects/challenge/api/main.py` | `def mcp_config() -> MCPConfigOut` | chunk_id=`main.py::structured::0052`
- `/home/nout/projects/challenge/chat_service.py` | `def _get_mcp_tool_specs_for_agent() -> list[ToolCallSpec]` | chunk_id=`chat_service.py::structured::0030`
- `/home/nout/projects/challenge/llm_agent.py` | `def _parse_json_object(text` | chunk_id=`llm_agent.py::structured::0031`
- `/home/nout/projects/challenge/docs/rag_antihallucination_report.md` | `heading:q02` | chunk_id=`rag_antihallucination_report.md::structured::0007`
- `/home/nout/projects/challenge/docs/rag_antihallucination_report.md` | `heading:q01` | chunk_id=`rag_antihallucination_report.md::structured::0002`
- `/home/nout/projects/challenge/docs/rag_rerank_comparison.md` | `heading:q01: Где в проекте выполняется маршрутизация вызовов MCP-инструментов по serverid__tool?` | chunk_id=`rag_rerank_comparison.md::structured::0004`
- `/home/nout/projects/challenge/docs/rag_rerank_comparison.md` | `heading:q02: Как устроена поддержка нескольких MCP серверов через MCP_SERVERS_JSON?` | chunk_id=`rag_rerank_comparison.md::structured::0011`

### Рекомендации
- `/home/nout/projects/challenge/api/main.py` | `def mcp_config() -> MCPConfigOut` | chunk_id=`main.py::structured::0051`
- `/home/nout/projects/challenge/api/main.py` | `def mcp_config() -> MCPConfigOut` | chunk_id=`main.py::structured::0052`
- `/home/nout/projects/challenge/chat_service.py` | `def _get_mcp_tool_specs_for_agent() -> list[ToolCallSpec]` | chunk_id=`chat_service.py::structured::0030`
- `/home/nout/projects/challenge/llm_agent.py` | `def _parse_json_object(text` | chunk_id=`llm_agent.py::structured::0031`
- `/home/nout/projects/challenge/docs/rag_antihallucination_report.md` | `heading:q02` | chunk_id=`rag_antihallucination_report.md::structured::0007`
- `/home/nout/projects/challenge/docs/rag_antihallucination_report.md` | `heading:q01` | chunk_id=`rag_antihallucination_report.md::structured::0002`
- `/home/nout/projects/challenge/docs/rag_rerank_comparison.md` | `heading:q01: Где в проекте выполняется маршрутизация вызовов MCP-инструментов по serverid__tool?` | chunk_id=`rag_rerank_comparison.md::structured::0004`
- `/home/nout/projects/challenge/docs/rag_rerank_comparison.md` | `heading:q02: Как устроена поддержка нескольких MCP серверов через MCP_SERVERS_JSON?` | chunk_id=`rag_rerank_comparison.md::structured::0011`
