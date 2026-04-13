# RAG Chunking Comparison

- Database: `/home/nout/projects/challenge/rag_index.db`
- Query count: 8
- Top-k: 3
- Query embedding model: `text-embedding-3-small`

## Corpus Stats

- Fixed chunks: 272
- Structured chunks: 342

## Retrieval Side-by-Side

### Query 1

`Где в проекте выполняется маршрутизация вызовов MCP инструментов?`

**Fixed-size top hits**
- score=0.1616 | file=`/home/nout/projects/challenge/api/main.py` | section=`file:main.py` | chunk_id=`main.py::fixed::0015`
- score=0.1463 | file=`/home/nout/projects/challenge/chat_service.py` | section=`file:chat_service.py` | chunk_id=`chat_service.py::fixed::0027`
- score=0.1423 | file=`/home/nout/projects/challenge/mcp_client.py` | section=`file:mcp_client.py` | chunk_id=`mcp_client.py::fixed::0003`

**Structured top hits**
- score=0.2236 | file=`/home/nout/projects/challenge/api/main.py` | section=`def create_invariant_api(` | chunk_id=`main.py::structured::0073`
- score=0.1581 | file=`/home/nout/projects/challenge/api/main.py` | section=`def mcp_config() -> MCPConfigOut` | chunk_id=`main.py::structured::0050`
- score=0.1291 | file=`/home/nout/projects/challenge/chat_service.py` | section=`def send_message(` | chunk_id=`chat_service.py::structured::0043`

### Query 2

`Как устроен потоковый ответ ассистента через SSE?`

**Fixed-size top hits**
- score=0.3160 | file=`/home/nout/projects/challenge/sqlite_chat_storage.py` | section=`file:sqlite_chat_storage.py` | chunk_id=`sqlite_chat_storage.py::fixed::0015`
- score=0.2523 | file=`/home/nout/projects/challenge/api/main.py` | section=`file:main.py` | chunk_id=`main.py::fixed::0002`
- score=0.2285 | file=`/home/nout/projects/challenge/sqlite_chat_storage.py` | section=`file:sqlite_chat_storage.py` | chunk_id=`sqlite_chat_storage.py::fixed::0012`

**Structured top hits**
- score=0.3385 | file=`/home/nout/projects/challenge/sqlite_chat_storage.py` | section=`class BranchInfo` | chunk_id=`sqlite_chat_storage.py::structured::0001`
- score=0.3319 | file=`/home/nout/projects/challenge/api/main.py` | section=`class BranchOut(BaseModel)` | chunk_id=`main.py::structured::0003`
- score=0.3086 | file=`/home/nout/projects/challenge/sqlite_chat_storage.py` | section=`class SQLiteChatStorage` | chunk_id=`sqlite_chat_storage.py::structured::0019`

### Query 3

`Где читаются MCP настройки из .env?`

**Fixed-size top hits**
- score=0.1837 | file=`/home/nout/projects/challenge/api/main.py` | section=`file:main.py` | chunk_id=`main.py::fixed::0001`
- score=0.1751 | file=`/home/nout/projects/challenge/mcp_client.py` | section=`file:mcp_client.py` | chunk_id=`mcp_client.py::fixed::0000`
- score=0.1329 | file=`/home/nout/projects/challenge/frontend/src/App.tsx` | section=`file:App.tsx` | chunk_id=`App.tsx::fixed::0035`

**Structured top hits**
- score=0.2070 | file=`/home/nout/projects/challenge/api/main.py` | section=`def _sse(event` | chunk_id=`main.py::structured::0026`
- score=0.1329 | file=`/home/nout/projects/challenge/frontend/src/App.tsx` | section=`file:App.tsx` | chunk_id=`App.tsx::structured::0035`
- score=0.1260 | file=`/home/nout/projects/challenge/app_settings.py` | section=`class MemoryStrategyDefaults` | chunk_id=`app_settings.py::structured::0019`

### Query 4

`Как реализован function calling у LLM агента?`

**Fixed-size top hits**
- score=0.2187 | file=`/home/nout/projects/challenge/api/main.py` | section=`file:main.py` | chunk_id=`main.py::fixed::0001`
- score=0.2107 | file=`/home/nout/projects/challenge/sqlite_chat_storage.py` | section=`file:sqlite_chat_storage.py` | chunk_id=`sqlite_chat_storage.py::fixed::0015`
- score=0.2040 | file=`/home/nout/projects/challenge/llm_agent.py` | section=`file:llm_agent.py` | chunk_id=`llm_agent.py::fixed::0021`

**Structured top hits**
- score=0.2904 | file=`/home/nout/projects/challenge/api/main.py` | section=`class BranchOut(BaseModel)` | chunk_id=`main.py::structured::0003`
- score=0.2633 | file=`/home/nout/projects/challenge/sqlite_chat_storage.py` | section=`class BranchInfo` | chunk_id=`sqlite_chat_storage.py::structured::0001`
- score=0.2279 | file=`/home/nout/projects/challenge/api/main.py` | section=`class ChatOut(BaseModel)` | chunk_id=`main.py::structured::0002`

### Query 5

`Где определяется API endpoint для погоды Иркутска?`

**Fixed-size top hits**
- score=0.1535 | file=`/home/nout/projects/challenge/frontend/src/api.ts` | section=`file:api.ts` | chunk_id=`api.ts::fixed::0001`
- score=0.1370 | file=`/home/nout/projects/challenge/frontend/src/api.ts` | section=`file:api.ts` | chunk_id=`api.ts::fixed::0013`
- score=0.1339 | file=`/home/nout/projects/challenge/frontend/src/api.ts` | section=`file:api.ts` | chunk_id=`api.ts::fixed::0002`

**Structured top hits**
- score=0.1690 | file=`/home/nout/projects/challenge/api/main.py` | section=`def patch_branch(` | chunk_id=`main.py::structured::0056`
- score=0.1535 | file=`/home/nout/projects/challenge/frontend/src/api.ts` | section=`file:api.ts` | chunk_id=`api.ts::structured::0001`
- score=0.1370 | file=`/home/nout/projects/challenge/frontend/src/api.ts` | section=`file:api.ts` | chunk_id=`api.ts::structured::0013`

### Query 6

`Где хранится и обновляется рабочая память ветки?`

**Fixed-size top hits**
- score=0.2475 | file=`/home/nout/projects/challenge/llm_agent.py` | section=`file:llm_agent.py` | chunk_id=`llm_agent.py::fixed::0011`
- score=0.2404 | file=`/home/nout/projects/challenge/api/main.py` | section=`file:main.py` | chunk_id=`main.py::fixed::0010`
- score=0.1987 | file=`/home/nout/projects/challenge/api/main.py` | section=`file:main.py` | chunk_id=`main.py::fixed::0009`

**Structured top hits**
- score=0.2503 | file=`/home/nout/projects/challenge/chat_service.py` | section=`def get_task_fsm_state(storage` | chunk_id=`chat_service.py::structured::0015`
- score=0.2412 | file=`/home/nout/projects/challenge/llm_agent.py` | section=`class LLMAgent` | chunk_id=`llm_agent.py::structured::0016`
- score=0.2385 | file=`/home/nout/projects/challenge/api/main.py` | section=`def _weather_from_wttr() -> WeatherPopupOut` | chunk_id=`main.py::structured::0031`

### Query 7

`Как устроен список и ping MCP серверов?`

**Fixed-size top hits**
- score=0.3333 | file=`/home/nout/projects/challenge/api/main.py` | section=`file:main.py` | chunk_id=`main.py::fixed::0017`
- score=0.2791 | file=`/home/nout/projects/challenge/api/main.py` | section=`file:main.py` | chunk_id=`main.py::fixed::0015`
- score=0.2678 | file=`/home/nout/projects/challenge/frontend/src/api.ts` | section=`file:api.ts` | chunk_id=`api.ts::fixed::0002`

**Structured top hits**
- score=0.3438 | file=`/home/nout/projects/challenge/api/main.py` | section=`def mcp_config() -> MCPConfigOut` | chunk_id=`main.py::structured::0044`
- score=0.3419 | file=`/home/nout/projects/challenge/api/main.py` | section=`class ChatOut(BaseModel)` | chunk_id=`main.py::structured::0002`
- score=0.3385 | file=`/home/nout/projects/challenge/sqlite_chat_storage.py` | section=`class BranchInfo` | chunk_id=`sqlite_chat_storage.py::structured::0001`

### Query 8

`Где в фронтенде вызывается weather popup?`

**Fixed-size top hits**
- score=0.2691 | file=`/home/nout/projects/challenge/frontend/src/api.ts` | section=`file:api.ts` | chunk_id=`api.ts::fixed::0009`
- score=0.2506 | file=`/home/nout/projects/challenge/frontend/src/App.tsx` | section=`file:App.tsx` | chunk_id=`App.tsx::fixed::0009`
- score=0.2373 | file=`/home/nout/projects/challenge/frontend/src/api.ts` | section=`file:api.ts` | chunk_id=`api.ts::fixed::0000`

**Structured top hits**
- score=0.2691 | file=`/home/nout/projects/challenge/frontend/src/api.ts` | section=`file:api.ts` | chunk_id=`api.ts::structured::0009`
- score=0.2506 | file=`/home/nout/projects/challenge/frontend/src/App.tsx` | section=`file:App.tsx` | chunk_id=`App.tsx::structured::0009`
- score=0.2373 | file=`/home/nout/projects/challenge/frontend/src/api.ts` | section=`file:api.ts` | chunk_id=`api.ts::structured::0000`

## Quick Summary

- Avg best-score fixed: `0.2354`
- Avg best-score structured: `0.2615`
- Structured strategy usually gives more interpretable `section` metadata.
- Fixed strategy often yields more uniform chunk lengths and simpler tuning.

## Auto Conclusion

- По средней top-1 схожести structured выглядит предпочтительнее на текущем корпусе.
- Для кода structured обычно удобнее для объяснимости (section = class/def), fixed проще и стабильнее в настройке.

## Manual Conclusion Template

- Где fixed оказался лучше: ...
- Где structured оказался лучше: ...
- Что выбрано как дефолт и почему: ...
