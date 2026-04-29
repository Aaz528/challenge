# PR Review (Assistant + RAG)

- Range: `HEAD~1...HEAD`
- Changed files: **5**

## Потенциальные баги

Потенциальные баги: 1) В `_run_rag_help` нет проверки, что `rag_qa.py` существует — если скрипт отсутствует, `subprocess.run` вызовет `FileNotFoundError`. 2) В `_handle_help_command` не обрабатывается случай, когда `storage.append_message` или `storage.get_branch` выбрасывает исключение (например, при повреждении БД). 3) В `mcp_project_git_demo` нет проверки, что `session_from_profile` успешно создаёт сессию — если профиль некорректен, может быть необработанное исключение. 4) В `project_git_mcp.py` `_run_git` не обрабатывает `TimeoutExpired` — при зависании git-команды вызов упадёт с `subprocess.TimeoutExpired`.

## Архитектурные проблемы

Архитектурные проблемы: 1) В `_run_rag_help` нет проверки существования скрипта `rag_qa.py` — при его отсутствии `subprocess.run` вызовет `FileNotFoundError`. 2) В `_handle_help_command` не обрабатываются исключения от `storage.append_message` или `storage.get_branch` (например, при повреждении БД). 3) В `mcp_project_git_demo` нет проверки успешности `session_from_profile` — при некорректном профиле может быть необработанное исключение. 4) В `project_git_mcp.py` `_run_git` не обрабатывает `TimeoutExpired` — при зависании git-команды вызов упадёт с `subprocess.TimeoutExpired`.

## Рекомендации

Рекомендации по улучшению: 1) В `_run_rag_help` (chat_service.py) добавить проверку существования скрипта `rag_qa.py` перед вызовом `subprocess.run`, чтобы избежать `FileNotFoundError`. 2) В `_handle_help_command` (chat_service.py) обработать исключения от `storage.append_message` и `storage.get_branch` (например, при повреждении БД). 3) В `mcp_project_git_demo` (api/main.py) проверить успешность создания сессии через `session_from_profile`. 4) В `project_git_mcp.py` обработать `subprocess.TimeoutExpired` в `_run_git`.

## Источники (RAG)

### Баги
- `/home/nout/projects/challenge/llm_agent.py` | `class LLMAgent` | chunk_id=`llm_agent.py::structured::0013`
- `/home/nout/projects/challenge/frontend/src/App.tsx` | `file:App.tsx` | chunk_id=`App.tsx::structured::0028`
- `/home/nout/projects/challenge/llm_agent.py` | `class LLMAgent` | chunk_id=`llm_agent.py::structured::0012`
- `/home/nout/projects/challenge/api/main.py` | `def _sse(event` | chunk_id=`main.py::structured::0026`
- `/home/nout/projects/challenge/mcp_client.py` | `def tool_to_dict(tool` | chunk_id=`mcp_client.py::structured::0001`
- `/home/nout/projects/challenge/chat_service.py` | `def build_triple_context(` | chunk_id=`chat_service.py::structured::0021`
- `/home/nout/projects/challenge/chat_service.py` | `def build_triple_context(` | chunk_id=`chat_service.py::structured::0022`
- `/home/nout/projects/challenge/api/main.py` | `def get_weather_irkutsk() -> WeatherPopupOut` | chunk_id=`main.py::structured::0033`

### Архитектура
- `/home/nout/projects/challenge/llm_agent.py` | `class LLMAgent` | chunk_id=`llm_agent.py::structured::0013`
- `/home/nout/projects/challenge/frontend/src/App.tsx` | `file:App.tsx` | chunk_id=`App.tsx::structured::0028`
- `/home/nout/projects/challenge/llm_agent.py` | `class LLMAgent` | chunk_id=`llm_agent.py::structured::0012`
- `/home/nout/projects/challenge/api/main.py` | `def _sse(event` | chunk_id=`main.py::structured::0026`
- `/home/nout/projects/challenge/mcp_client.py` | `def tool_to_dict(tool` | chunk_id=`mcp_client.py::structured::0001`
- `/home/nout/projects/challenge/chat_service.py` | `def build_triple_context(` | chunk_id=`chat_service.py::structured::0021`
- `/home/nout/projects/challenge/chat_service.py` | `def build_triple_context(` | chunk_id=`chat_service.py::structured::0022`
- `/home/nout/projects/challenge/api/main.py` | `def get_weather_irkutsk() -> WeatherPopupOut` | chunk_id=`main.py::structured::0033`

### Рекомендации
- `/home/nout/projects/challenge/llm_agent.py` | `class LLMAgent` | chunk_id=`llm_agent.py::structured::0013`
- `/home/nout/projects/challenge/frontend/src/App.tsx` | `file:App.tsx` | chunk_id=`App.tsx::structured::0028`
- `/home/nout/projects/challenge/llm_agent.py` | `class LLMAgent` | chunk_id=`llm_agent.py::structured::0012`
- `/home/nout/projects/challenge/api/main.py` | `def _sse(event` | chunk_id=`main.py::structured::0026`
- `/home/nout/projects/challenge/mcp_client.py` | `def tool_to_dict(tool` | chunk_id=`mcp_client.py::structured::0001`
- `/home/nout/projects/challenge/chat_service.py` | `def build_triple_context(` | chunk_id=`chat_service.py::structured::0021`
- `/home/nout/projects/challenge/chat_service.py` | `def build_triple_context(` | chunk_id=`chat_service.py::structured::0022`
- `/home/nout/projects/challenge/api/main.py` | `def get_weather_irkutsk() -> WeatherPopupOut` | chunk_id=`main.py::structured::0033`
