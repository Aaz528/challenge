from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app_settings import (
    INVARIANT_CATEGORIES,
    INVARIANT_SEVERITIES,
    MCPSettings,
    MEMORY_PROFILE_PRESETS,
    MEMORY_STRATEGIES,
    SETTINGS,
    WEB_SETTINGS,
    load_mcp_server_profiles,
    load_mcp_settings,
)
from chat_service import (
    TaskFSMState,
    pause_task_fsm,
    resume_task_fsm,
    resume_last_answer_stream,
    send_message,
    send_message_stream,
    set_task_fsm_state,
    transition_task_fsm,
    get_task_fsm_state,
)
from sqlite_chat_storage import BranchInfo, InvariantRow, SQLiteChatStorage

from api.deps import get_storage

# MCP_* и прочие переменные из .env (без этого только llm_agent подхватывал бы ключи при первом LLM-вызове)
_project_root = Path(__file__).resolve().parents[1]
load_dotenv(_project_root / ".env")
load_dotenv()

app = FastAPI(title="LLM Agent API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(WEB_SETTINGS.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_stream_stop_lock = threading.Lock()
_stream_stops: dict[tuple[int, int], threading.Event] = {}

# Таймаут ожидания MCP connect/list-tools (сек).
# Настраивается через MCP_CONNECT_TIMEOUT_SEC в .env:
# - > 0: лимит в секундах
# - 0 или отрицательное: без лимита
def _mcp_connect_timeout_sec() -> float:
    raw = os.environ.get("MCP_CONNECT_TIMEOUT_SEC", "180").strip()
    try:
        return float(raw or "180")
    except ValueError:
        return 180.0


def _mcp_error_detail(exc: Exception) -> str:
    """
    Разворачивает ExceptionGroup/TaskGroup ошибки в читаемую причину.
    Иначе пользователю приходит бесполезное "unhandled errors in a TaskGroup".
    """
    seen: set[int] = set()
    stack: list[BaseException] = [exc]
    parts: list[str] = []
    while stack:
        cur = stack.pop()
        obj_id = id(cur)
        if obj_id in seen:
            continue
        seen.add(obj_id)
        msg = str(cur).strip()
        name = cur.__class__.__name__
        if msg:
            parts.append(f"{name}: {msg}")
        # ExceptionGroup (py3.11+) / anyio task groups
        sub = getattr(cur, "exceptions", None)
        if isinstance(sub, tuple):
            stack.extend(sub)
    if not parts:
        return str(exc)
    return " | ".join(parts[:4])


class ChatOut(BaseModel):
    id: int
    title: str
    total_tokens: int


class BranchOut(BaseModel):
    id: int
    title: str
    parent_branch_id: int | None
    fork_after_message_id: int | None
    system_prompt: str
    temperature: float
    max_tokens: int
    timeout_sec: float
    total_tokens: int
    memory_strategy: str
    strategy_params_json: str


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    summarized: bool


class CreateChatBody(BaseModel):
    title: str | None = None


class SendMessageBody(BaseModel):
    content: str


class SendMessageResponse(BaseModel):
    assistant_text: str
    model: str
    tokens_this_turn: int | None
    total_tokens_branch: int
    total_tokens_chat: int
    elapsed_sec: float


class MemoryItemOut(BaseModel):
    key: str
    value: str
    updated_at: str


class PutMemoryBody(BaseModel):
    value: str


class MemoryProfileOut(BaseModel):
    id: str
    title: str
    description: str
    user_id: str


class TaskFSMOut(BaseModel):
    stage: str
    current_step: str
    expected_action: str
    previous_stage: str | None = None
    pause_reason: str | None = None


class PatchTaskFSMBody(BaseModel):
    stage: str | None = None
    current_step: str | None = None
    expected_action: str | None = None


class PauseTaskBody(BaseModel):
    reason: str | None = None


class InvariantOut(BaseModel):
    id: int
    user_id: str
    category: str
    severity: str
    title: str
    statement: str
    active: bool
    updated_at: str


class InvariantCreateBody(BaseModel):
    category: str
    severity: str
    title: str
    statement: str


class InvariantPatchBody(BaseModel):
    category: str | None = None
    severity: str | None = None
    title: str | None = None
    statement: str | None = None
    active: bool | None = None


class ForkBody(BaseModel):
    fork_after_message_id: int = Field(..., description="ID сообщения в текущей ветке — история до него включительно копируется")
    title: str = "Новая ветка"
    system_prompt: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    timeout_sec: float | None = None


class PatchBranchBody(BaseModel):
    title: str | None = None
    system_prompt: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    timeout_sec: float | None = None
    memory_strategy: str | None = None
    strategy_params_json: str | None = None


def _normalize_memory_strategy_api(raw: str | None) -> str | None:
    if raw is None:
        return None
    s = raw.strip().lower()
    if s not in MEMORY_STRATEGIES:
        raise ValueError(f"Неизвестная стратегия памяти: {raw!r}")
    return s


def _normalize_strategy_params_json(raw: str | None) -> str | None:
    if raw is None:
        return None
    t = raw.strip()
    if not t:
        return "{}"
    try:
        obj = json.loads(t)
    except json.JSONDecodeError as e:
        raise ValueError("strategy_params_json: невалидный JSON") from e
    if not isinstance(obj, dict):
        raise ValueError("strategy_params_json: ожидается JSON-объект")
    return json.dumps(obj, ensure_ascii=False)


def _branch_out(b: BranchInfo) -> BranchOut:
    return BranchOut(
        id=b.branch_id,
        title=b.title,
        parent_branch_id=b.parent_branch_id,
        fork_after_message_id=b.fork_after_message_id,
        system_prompt=b.system_prompt,
        temperature=b.temperature,
        max_tokens=b.max_tokens,
        timeout_sec=b.timeout_sec,
        total_tokens=b.total_tokens,
        memory_strategy=b.memory_strategy,
        strategy_params_json=b.strategy_params_json,
    )


def _task_out(state: TaskFSMState) -> TaskFSMOut:
    return TaskFSMOut(
        stage=state.stage,
        current_step=state.current_step,
        expected_action=state.expected_action,
        previous_stage=state.previous_stage,
        pause_reason=state.pause_reason,
    )


def _normalize_invariant_category(raw: str) -> str:
    s = (raw or "").strip().lower()
    if s not in INVARIANT_CATEGORIES:
        raise ValueError(f"Неизвестная категория инварианта: {raw!r}")
    return s


def _normalize_invariant_severity(raw: str) -> str:
    s = (raw or "").strip().lower()
    if s not in INVARIANT_SEVERITIES:
        raise ValueError(f"Неизвестная строгость: {raw!r}")
    return s


def _invariant_out(r: InvariantRow) -> InvariantOut:
    return InvariantOut(
        id=r.invariant_id,
        user_id=r.user_id,
        category=r.category,
        severity=r.severity,
        title=r.title,
        statement=r.statement,
        active=bool(r.active),
        updated_at=r.updated_at,
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


class WeatherPopupOut(BaseModel):
    city: str
    temperature_c: float
    wind_speed_kmh: float
    weather_code: int
    time_local: str
    source: str = "open-meteo.com"


# Иркутск (центр города), для Yandex Weather API
_IRKUTSK_LAT = 52.2869741
_IRKUTSK_LON = 104.3050183

# Условные коды WMO-подобные для отображения (как у wttr); см. документацию Yandex fact.condition
_YANDEX_CONDITION_TO_WMO: dict[str, int] = {
    "clear": 0,
    "partly-cloudy": 2,
    "cloudy": 3,
    "overcast": 3,
    "partly-cloudy-and-light-rain": 61,
    "partly-cloudy-and-rain": 63,
    "overcast-and-rain": 65,
    "overcast-thunderstorms-with-rain": 95,
    "cloudy-and-light-rain": 61,
    "overcast-and-light-rain": 61,
    "cloudy-and-rain": 63,
    "overcast-and-wet-snow": 69,
    "partly-cloudy-and-light-snow": 71,
    "partly-cloudy-and-snow": 73,
    "overcast-and-snow": 75,
    "cloudy-and-light-snow": 71,
    "overcast-and-light-snow": 73,
    "cloudy-and-snow": 73,
}


def _weather_from_yandex() -> WeatherPopupOut:
    key = os.environ.get("YANDEX_WEATHER_KEY", "").strip()
    if not key:
        raise ValueError("YANDEX_WEATHER_KEY не задан")
    r = requests.get(
        "https://api.weather.yandex.ru/v1/forecast",
        params={
            "lat": _IRKUTSK_LAT,
            "lon": _IRKUTSK_LON,
            "lang": "ru_RU",
            "limit": 1,
            "hours": "false",
        },
        headers={"X-Yandex-Weather-Key": key},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    fact = data.get("fact") if isinstance(data, dict) else None
    if not isinstance(fact, dict):
        raise ValueError("Нет поля fact")
    temp = float(fact["temp"])
    wind_ms = float(fact.get("wind_speed") or 0.0)
    wind_kmh = wind_ms * 3.6
    cond = fact.get("condition")
    code = _YANDEX_CONDITION_TO_WMO.get(str(cond), -1) if cond is not None else -1
    obs = fact.get("obs_time")
    if isinstance(obs, (int, float)) and obs > 0:
        t_local = datetime.utcfromtimestamp(int(obs)).strftime("%Y-%m-%d %H:%M UTC")
    else:
        t_local = str(data.get("now_dt") or "")
    return WeatherPopupOut(
        city="Иркутск",
        temperature_c=temp,
        wind_speed_kmh=wind_kmh,
        weather_code=code,
        time_local=t_local,
        source="api.weather.yandex.ru",
    )


def _weather_from_wttr() -> WeatherPopupOut:
    r2 = requests.get("https://wttr.in/Irkutsk", params={"format": "j1"}, timeout=20)
    r2.raise_for_status()
    data2 = r2.json()
    cur = data2.get("current_condition") if isinstance(data2, dict) else None
    first = cur[0] if isinstance(cur, list) and cur else None
    if not isinstance(first, dict):
        raise ValueError("Некорректный ответ current_condition")
    temp = float(first.get("temp_C"))
    wind = float(first.get("windspeedKmph"))
    code = int(first.get("weatherCode"))
    t_local = str(first.get("localObsDateTime") or first.get("observation_time") or "")
    return WeatherPopupOut(
        city="Иркутск",
        temperature_c=temp,
        wind_speed_kmh=wind,
        weather_code=code,
        time_local=t_local,
        source="wttr.in",
    )


_weather_cache_irkutsk: WeatherPopupOut | None = None


@app.get("/api/weather/irkutsk", response_model=WeatherPopupOut)
def get_weather_irkutsk() -> WeatherPopupOut:
    """Погода в Иркутске: при YANDEX_WEATHER_KEY — Яндекс, иначе wttr.in; при сбоях — кеш или заглушка."""
    global _weather_cache_irkutsk
    try:
        key = os.environ.get("YANDEX_WEATHER_KEY", "").strip()
        if key:
            out = _weather_from_yandex()
        else:
            out = _weather_from_wttr()
        _weather_cache_irkutsk = out
        return out
    except Exception:
        try:
            out = _weather_from_wttr()
            _weather_cache_irkutsk = out
            return out
        except Exception as e2:
            if _weather_cache_irkutsk is not None:
                # Отдаём последнее успешное значение, чтобы попап не ломал UX.
                return WeatherPopupOut(
                    city=_weather_cache_irkutsk.city,
                    temperature_c=_weather_cache_irkutsk.temperature_c,
                    wind_speed_kmh=_weather_cache_irkutsk.wind_speed_kmh,
                    weather_code=_weather_cache_irkutsk.weather_code,
                    time_local=_weather_cache_irkutsk.time_local,
                    source=f"{_weather_cache_irkutsk.source} (cached)",
                )
            # Совсем без сети: отдаём нейтральный fallback вместо ошибки.
            return WeatherPopupOut(
                city="Иркутск",
                temperature_c=0.0,
                wind_speed_kmh=0.0,
                weather_code=-1,
                time_local=datetime.now().strftime("%Y-%m-%d %H:%M"),
                source=f"fallback (network unavailable: {e2.__class__.__name__})",
            )


class MCPConfigOut(BaseModel):
    """Снимок настроек клиента MCP (без секретов)."""

    enabled: bool
    transport: str
    stdio_command: str
    streamable_http_url: str
    http_timeout_sec: float
    # URL не localhost — удалённый MCP (нагрузка на другом хосте)
    looks_like_remote_streamable: bool = False
    streamable_http_headers_configured: bool = False
    hint: str | None = None
    # Несколько серверов (MCP_SERVERS_JSON)
    mcp_server_ids: list[str] = Field(default_factory=list)
    mcp_servers_json_configured: bool = False


def _mcp_url_looks_remote(url: str) -> bool:
    u = (url or "").strip().lower()
    if not u:
        return False
    if "127.0.0.1" in u or "localhost" in u:
        return False
    return u.startswith("http://") or u.startswith("https://")


def _mcp_config_hint(s: MCPSettings) -> str | None:
    if not s.enabled:
        return None
    tr = (s.transport or "").lower()
    if tr in ("streamable_http", "http", "streamable-http"):
        u = (s.streamable_http_url or "").strip()
        if not u:
            return (
                "Задайте MCP_STREAMABLE_HTTP_URL — это URL отдельного MCP-сервера (Streamable HTTP), "
                "а не REST этого API, если вы не монтируете MCP в том же процессе."
            )
        port = WEB_SETTINGS.port
        for needle in (f"127.0.0.1:{port}", f"localhost:{port}"):
            if needle in u:
                return (
                    f"URL указывает на порт {port}. Если там только uvicorn этого приложения и нет endpoint MCP, "
                    "запрос будет долго ждать или падать. Поднимите MCP на другом порту (например FastMCP) "
                    "или вернитесь к транспорту stdio."
                )
    return None


class MCPPingOut(BaseModel):
    ok: bool
    message: str


class MCPToolsOut(BaseModel):
    ok: bool
    tools: list[dict[str, Any]]
    tool_count: int


class MCPPipelineBody(BaseModel):
    query: str
    limit: int = Field(default=5, ge=1, le=20)
    max_chars: int = Field(default=500, ge=80, le=6000)
    max_points: int = Field(default=5, ge=1, le=20)
    output_file: str = "outputs/mcp_pipeline_summary.txt"
    overwrite: bool = True


class MCPPipelineOut(BaseModel):
    ok: bool
    query: str
    search_raw: str
    summarize_raw: str
    save_raw: str


class MCPProjectGitDemoBody(BaseModel):
    """Учебный прогон git-инструментов MCP: branch + files + diff."""

    file_limit: int = Field(default=20, ge=1, le=500)
    include_untracked: bool = False
    diff_max_chars: int = Field(default=3000, ge=200, le=50000)
    diff_staged: bool = False
    diff_ref: str = ""
    diff_file_path: str = ""


class MCPProjectGitDemoOut(BaseModel):
    ok: bool
    server_id: str
    branch_raw: str
    files_raw: str
    diff_raw: str


class SupportAskBody(BaseModel):
    question: str
    user_id: str | None = None
    ticket_id: str | None = None
    top_k_before: int = Field(default=20, ge=1, le=100)
    top_k_after: int = Field(default=6, ge=1, le=50)
    sim_threshold: float = 0.12


class RAGQueryBody(BaseModel):
    question: str
    mode: str = "both"  # without_rag | with_rag | both
    strategy: str = "structured"  # fixed | structured | all
    top_k_before: int = Field(default=20, ge=1, le=100)
    top_k_after: int = Field(default=5, ge=1, le=50)
    sim_threshold: float = 0.12
    answer_min_score: float | None = Field(
        default=None,
        description="Мин. score лучшего чанка; ниже — «не знаю». None = RAG_ANSWER_MIN_SCORE или sim_threshold.",
    )
    rerank_mode: str = "hybrid"  # none | threshold | hybrid
    rewrite_mode: str = "heuristic"  # none | heuristic
    max_context_chars: int = Field(default=6000, ge=800, le=30000)
    force_local: bool = False


class RAGBenchmarkBody(BaseModel):
    strategy: str = "structured"  # fixed | structured | all
    top_k_before: int = Field(default=20, ge=1, le=100)
    top_k_after: int = Field(default=5, ge=1, le=50)
    sim_threshold: float = 0.12
    force_local: bool = False


class RagMiniChatTurnBody(BaseModel):
    """Один ход мини-чата RAG + память задачи (история и task_memory приходит с клиента)."""

    message: str
    history: list[dict[str, Any]] = Field(default_factory=list)
    task_memory: dict[str, Any] = Field(default_factory=dict)
    strategy: str = "structured"
    top_k_before: int = Field(default=20, ge=1, le=100)
    top_k_after: int = Field(default=5, ge=1, le=50)
    sim_threshold: float = 0.12
    max_context_chars: int = Field(default=5000, ge=800, le=30000)


def _parse_json_text_or_none(raw: str) -> dict[str, Any] | None:
    try:
        obj = json.loads(raw)
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def _run_script_json(script_name: str, args: list[str], *, force_local: bool = False) -> dict[str, Any]:
    script_path = _project_root / "scripts" / script_name
    if not script_path.exists():
        raise RuntimeError(f"Script not found: {script_path}")
    env = os.environ.copy()
    if force_local:
        env["RAG_QA_FORCE_LOCAL"] = "1"
    cmd = [sys.executable, str(script_path), *args, "--json"]
    proc = subprocess.run(
        cmd,
        cwd=str(_project_root),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "").strip() or f"Script failed: {script_name}")
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Script returned invalid JSON: {script_name}") from e
    if not isinstance(out, dict):
        raise RuntimeError(f"Script returned non-object JSON: {script_name}")
    return out


@app.get("/api/mcp/config", response_model=MCPConfigOut)
def mcp_config() -> MCPConfigOut:
    """Показывает, включён ли MCP и какой транспорт ожидается (без установки соединения)."""
    s = load_mcp_settings()
    url = s.streamable_http_url
    if url and len(url) > 24:
        url = url[:12] + "…" + url[-10:]
    return MCPConfigOut(
        enabled=s.enabled,
        transport=s.transport,
        stdio_command=s.stdio_command,
        streamable_http_url=url,
        http_timeout_sec=s.http_timeout_sec,
        looks_like_remote_streamable=_mcp_url_looks_remote(s.streamable_http_url),
        streamable_http_headers_configured=bool(s.streamable_http_headers),
        hint=_mcp_config_hint(s),
    )


@app.get("/api/mcp/ping", response_model=MCPPingOut)
async def mcp_ping() -> MCPPingOut:
    """Проверяет ping для каждого зарегистрированного MCP-сервера."""
    from mcp_client import session_from_profile

    profiles = load_mcp_server_profiles()
    if not profiles:
        raise HTTPException(
            status_code=503,
            detail="MCP выключен или список серверов пуст. Задайте MCP_ENABLED=1 и MCP_SERVERS_JSON (или legacy MCP_*).",
        )
    timeout_sec = _mcp_connect_timeout_sec()
    try:
        for p in profiles:
            if timeout_sec > 0:
                async with asyncio.timeout(timeout_sec):
                    async with session_from_profile(p) as session:
                        await session.send_ping()
            else:
                async with session_from_profile(p) as session:
                    await session.send_ping()
    except TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=(
                f"MCP: таймаут {timeout_sec:g}s. Первый запуск через npx часто долго качает npm-пакеты "
                "на этой машине. Повторите позже или установите MCP-сервер глобально (`npm i -g …`) и в .env укажите "
                "прямой бинарник в MCP_STDIO_COMMAND без npx — старт будет быстрее."
            ),
        ) from None
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"MCP: {_mcp_error_detail(e)}") from e
    ids = ", ".join(p.id for p in profiles)
    return MCPPingOut(ok=True, message=f"Соединение установлено, ping успешен для серверов: {ids}.")


@app.get("/api/mcp/tools", response_model=MCPToolsOut)
async def mcp_tools() -> MCPToolsOut:
    """Подключается ко всем зарегистрированным MCP-серверам и возвращает объединённый список инструментов."""
    from mcp_client import list_tools_dicts, session_from_profile

    profiles = load_mcp_server_profiles()
    if not profiles:
        raise HTTPException(
            status_code=503,
            detail="MCP выключен или список серверов пуст.",
        )
    timeout_sec = _mcp_connect_timeout_sec()
    multi = len(profiles) > 1
    tools: list[dict[str, Any]] = []
    try:
        for p in profiles:
            if timeout_sec > 0:
                async with asyncio.timeout(timeout_sec):
                    async with session_from_profile(p) as session:
                        batch = await list_tools_dicts(session)
            else:
                async with session_from_profile(p) as session:
                    batch = await list_tools_dicts(session)
            for t in batch:
                td = dict(t)
                td["mcp_server"] = p.id
                if multi:
                    orig = str(td.get("name", "") or "")
                    td["original_name"] = orig
                    td["name"] = f"{p.id}__{orig}"
                tools.append(td)
    except TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=(
                f"MCP: таймаут {timeout_sec:g}s — см. подсказку в /api/mcp/ping (npx / первый запуск)."
            ),
        ) from None
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"MCP: {_mcp_error_detail(e)}") from e
    return MCPToolsOut(ok=True, tools=tools, tool_count=len(tools))


@app.post("/api/mcp/edu-pipeline", response_model=MCPPipelineOut)
async def mcp_edu_pipeline(body: MCPPipelineBody) -> MCPPipelineOut:
    """Учебный прогон MCP-пайплайна: search -> summarize -> saveToFile."""
    from mcp_client import call_tool_text, session_from_profile

    profiles = load_mcp_server_profiles()
    if not profiles:
        raise HTTPException(
            status_code=503,
            detail="MCP выключен или список серверов пуст.",
        )
    pref = os.environ.get("MCP_EDU_PIPELINE_SERVER_ID", "edu").strip()
    prof = next((p for p in profiles if p.id == pref), None)
    if prof is None:
        ids = ", ".join(p.id for p in profiles)
        raise HTTPException(
            status_code=503,
            detail=(
                f"Нет MCP-профиля с id={pref!r}. Задайте MCP_EDU_PIPELINE_SERVER_ID или добавьте сервер в MCP_SERVERS_JSON. "
                f"Сейчас доступны: {ids}"
            ),
        )
    query = body.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query не может быть пустым")

    timeout_sec = _mcp_connect_timeout_sec()

    async def _run_pipeline(session) -> tuple[str, str, str]:
        search_raw, search_err = await call_tool_text(
            session,
            "search",
            {"query": query, "limit": int(body.limit)},
        )
        if search_err:
            raise HTTPException(
                status_code=502,
                detail=f"MCP tool search failed: {search_raw or 'unknown error'}",
            )
        summarize_raw, summarize_err = await call_tool_text(
            session,
            "summarize",
            {
                "search_result": search_raw,
                "max_chars": int(body.max_chars),
                "max_points": int(body.max_points),
            },
        )
        if summarize_err:
            raise HTTPException(
                status_code=502,
                detail=f"MCP tool summarize failed: {summarize_raw or 'unknown error'}",
            )
        save_raw, save_err = await call_tool_text(
            session,
            "saveToFile",
            {
                "content": summarize_raw,
                "file_path": body.output_file,
                "overwrite": bool(body.overwrite),
            },
        )
        if save_err:
            raise HTTPException(
                status_code=502,
                detail=f"MCP tool saveToFile failed: {save_raw or 'unknown error'}",
            )
        return search_raw, summarize_raw, save_raw

    try:
        if timeout_sec > 0:
            async with asyncio.timeout(timeout_sec):
                async with session_from_profile(prof) as session:
                    search_raw, summarize_raw, save_raw = await _run_pipeline(session)
        else:
            async with session_from_profile(prof) as session:
                search_raw, summarize_raw, save_raw = await _run_pipeline(session)
    except TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=f"MCP: таймаут {timeout_sec:g}s при выполнении edu pipeline.",
        ) from None
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"MCP: {_mcp_error_detail(e)}") from e

    # Лёгкая проверка структуры, чтобы быстро выявить неверный контракт.
    if _parse_json_text_or_none(search_raw) is None:
        raise HTTPException(status_code=502, detail="search вернул не-JSON текст")
    if _parse_json_text_or_none(summarize_raw) is None:
        raise HTTPException(status_code=502, detail="summarize вернул не-JSON текст")
    if _parse_json_text_or_none(save_raw) is None:
        raise HTTPException(status_code=502, detail="saveToFile вернул не-JSON текст")

    return MCPPipelineOut(
        ok=True,
        query=query,
        search_raw=search_raw,
        summarize_raw=summarize_raw,
        save_raw=save_raw,
    )


@app.post("/api/mcp/project-git-demo", response_model=MCPProjectGitDemoOut)
async def mcp_project_git_demo(body: MCPProjectGitDemoBody) -> MCPProjectGitDemoOut:
    """Учебный прогон git MCP: currentBranch -> listProjectFiles -> gitDiff."""
    from mcp_client import call_tool_text, session_from_profile

    profiles = load_mcp_server_profiles()
    if not profiles:
        raise HTTPException(
            status_code=503,
            detail="MCP выключен или список серверов пуст.",
        )
    pref = os.environ.get("MCP_PROJECT_GIT_SERVER_ID", "projectgit").strip()
    prof = next((p for p in profiles if p.id == pref), None)
    if prof is None:
        ids = ", ".join(p.id for p in profiles)
        raise HTTPException(
            status_code=503,
            detail=(
                f"Нет MCP-профиля с id={pref!r}. Задайте MCP_PROJECT_GIT_SERVER_ID или добавьте сервер в MCP_SERVERS_JSON. "
                f"Сейчас доступны: {ids}"
            ),
        )
    timeout_sec = _mcp_connect_timeout_sec()

    async def _run_demo(session) -> tuple[str, str, str]:
        branch_raw, branch_err = await call_tool_text(session, "currentBranch", {})
        if branch_err:
            raise HTTPException(
                status_code=502,
                detail=f"MCP tool currentBranch failed: {branch_raw or 'unknown error'}",
            )
        files_raw, files_err = await call_tool_text(
            session,
            "listProjectFiles",
            {
                "limit": int(body.file_limit),
                "include_untracked": bool(body.include_untracked),
            },
        )
        if files_err:
            raise HTTPException(
                status_code=502,
                detail=f"MCP tool listProjectFiles failed: {files_raw or 'unknown error'}",
            )
        diff_raw, diff_err = await call_tool_text(
            session,
            "gitDiff",
            {
                "ref": body.diff_ref,
                "staged": bool(body.diff_staged),
                "file_path": body.diff_file_path,
                "max_chars": int(body.diff_max_chars),
            },
        )
        if diff_err:
            raise HTTPException(
                status_code=502,
                detail=f"MCP tool gitDiff failed: {diff_raw or 'unknown error'}",
            )
        return branch_raw, files_raw, diff_raw

    try:
        if timeout_sec > 0:
            async with asyncio.timeout(timeout_sec):
                async with session_from_profile(prof) as session:
                    branch_raw, files_raw, diff_raw = await _run_demo(session)
        else:
            async with session_from_profile(prof) as session:
                branch_raw, files_raw, diff_raw = await _run_demo(session)
    except TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=f"MCP: таймаут {timeout_sec:g}s при выполнении project-git demo.",
        ) from None
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"MCP: {_mcp_error_detail(e)}") from e

    # Контракт: инструменты возвращают JSON-строки.
    if _parse_json_text_or_none(branch_raw) is None:
        raise HTTPException(status_code=502, detail="currentBranch вернул не-JSON текст")
    if _parse_json_text_or_none(files_raw) is None:
        raise HTTPException(status_code=502, detail="listProjectFiles вернул не-JSON текст")
    if _parse_json_text_or_none(diff_raw) is None:
        raise HTTPException(status_code=502, detail="gitDiff вернул не-JSON текст")

    return MCPProjectGitDemoOut(
        ok=True,
        server_id=prof.id,
        branch_raw=branch_raw,
        files_raw=files_raw,
        diff_raw=diff_raw,
    )


@app.post("/api/support/ask")
async def support_ask(body: SupportAskBody) -> dict[str, Any]:
    """Мини-сервис саппорта: вопрос + контекст тикета/пользователя через MCP + RAG-ответ по docs/code."""
    q = body.question.strip()
    if not q:
        raise HTTPException(status_code=400, detail="question не может быть пустым")

    from mcp_client import call_tool_text, session_from_profile

    profiles = load_mcp_server_profiles()
    if not profiles:
        raise HTTPException(status_code=503, detail="MCP выключен или список серверов пуст.")
    pref = os.environ.get("MCP_SUPPORT_CRM_SERVER_ID", "supportcrm").strip()
    prof = next((p for p in profiles if p.id == pref), None)
    if prof is None:
        ids = ", ".join(p.id for p in profiles)
        raise HTTPException(
            status_code=503,
            detail=(
                f"Нет MCP-профиля с id={pref!r}. Задайте MCP_SUPPORT_CRM_SERVER_ID или добавьте сервер в MCP_SERVERS_JSON. "
                f"Сейчас доступны: {ids}"
            ),
        )

    timeout_sec = _mcp_connect_timeout_sec()
    user_raw = ""
    ticket_raw = ""

    async def _load_crm(session) -> tuple[str, str]:
        user_txt = ""
        ticket_txt = ""
        uid = (body.user_id or "").strip()
        tid = (body.ticket_id or "").strip()
        if tid:
            ticket_txt, ticket_err = await call_tool_text(session, "getTicket", {"ticket_id": tid})
            if ticket_err:
                raise HTTPException(status_code=502, detail=f"MCP tool getTicket failed: {ticket_txt or 'unknown error'}")
            obj = _parse_json_text_or_none(ticket_txt) or {}
            t = obj.get("ticket")
            if isinstance(t, dict) and not uid:
                uid = str(t.get("user_id", "")).strip()
        if uid:
            user_txt, user_err = await call_tool_text(session, "getUser", {"user_id": uid})
            if user_err:
                raise HTTPException(status_code=502, detail=f"MCP tool getUser failed: {user_txt or 'unknown error'}")
        return user_txt, ticket_txt

    try:
        if timeout_sec > 0:
            async with asyncio.timeout(timeout_sec):
                async with session_from_profile(prof) as session:
                    user_raw, ticket_raw = await _load_crm(session)
        else:
            async with session_from_profile(prof) as session:
                user_raw, ticket_raw = await _load_crm(session)
    except TimeoutError:
        raise HTTPException(status_code=504, detail=f"MCP: таймаут {timeout_sec:g}s при чтении CRM.") from None
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"MCP: {_mcp_error_detail(e)}") from e

    support_prompt = (
        "Ты ассистент поддержки пользователей. Отвечай по-русски и предлагай конкретные действия саппорту. "
        "Опирайся на документацию/код из RAG-контекста и данные пользователя/тикета ниже.\n\n"
        f"Вопрос клиента: {q}\n\n"
        f"Контекст пользователя (MCP getUser):\n{user_raw or '(нет)'}\n\n"
        f"Контекст тикета (MCP getTicket):\n{ticket_raw or '(нет)'}\n\n"
        "Сформируй ответ так: 1) вероятная причина, 2) шаги проверки, 3) что сделать пользователю."
    )

    scripts = str(_project_root / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from rag_qa import answer_with_rag

    rag = answer_with_rag(
        support_prompt,
        db_path=_project_root / "rag_index.db",
        strategy="structured",
        top_k_before=int(body.top_k_before),
        top_k_after=int(body.top_k_after),
        sim_threshold=float(body.sim_threshold),
        rewrite_mode="heuristic",
        rerank_mode="hybrid",
        max_context_chars=7500,
    )
    return {
        "ok": True,
        "question": q,
        "ticket_id": body.ticket_id,
        "user_id": body.user_id,
        "crm_server_id": prof.id,
        "crm_user_raw": user_raw,
        "crm_ticket_raw": ticket_raw,
        "support_answer": rag.get("answer", ""),
        "sources": rag.get("sources", []),
        "quotes": rag.get("quotes", []),
        "dont_know": rag.get("dont_know", False),
        "dont_know_reason": rag.get("dont_know_reason"),
    }


@app.post("/api/rag/query")
def rag_query(body: RAGQueryBody) -> dict[str, Any]:
    q = body.question.strip()
    if not q:
        raise HTTPException(status_code=400, detail="question не может быть пустым")
    mode = body.mode.strip().lower()
    if mode not in ("without_rag", "with_rag", "both"):
        raise HTTPException(status_code=400, detail="mode должен быть: without_rag | with_rag | both")
    strategy = body.strategy.strip().lower()
    if strategy not in ("fixed", "structured", "all"):
        raise HTTPException(status_code=400, detail="strategy должен быть: fixed | structured | all")
    rerank_mode = body.rerank_mode.strip().lower()
    if rerank_mode not in ("none", "threshold", "hybrid"):
        raise HTTPException(status_code=400, detail="rerank_mode должен быть: none | threshold | hybrid")
    rewrite_mode = body.rewrite_mode.strip().lower()
    if rewrite_mode not in ("none", "heuristic"):
        raise HTTPException(status_code=400, detail="rewrite_mode должен быть: none | heuristic")
    args = [
        "--question",
        q,
        "--mode",
        mode,
        "--strategy",
        strategy,
        "--top-k-before",
        str(body.top_k_before),
        "--top-k-after",
        str(body.top_k_after),
        "--sim-threshold",
        str(body.sim_threshold),
        "--rerank-mode",
        rerank_mode,
        "--rewrite-mode",
        rewrite_mode,
        "--max-context-chars",
        str(body.max_context_chars),
    ]
    if body.answer_min_score is not None:
        args.extend(["--answer-min-score", str(body.answer_min_score)])
    try:
        return _run_script_json("rag_qa.py", args, force_local=body.force_local)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"RAG query failed: {_mcp_error_detail(e)}") from e


@app.post("/api/rag/benchmark")
def rag_benchmark(body: RAGBenchmarkBody) -> dict[str, Any]:
    strategy = body.strategy.strip().lower()
    if strategy not in ("fixed", "structured", "all"):
        raise HTTPException(status_code=400, detail="strategy должен быть: fixed | structured | all")
    script_path = _project_root / "scripts" / "eval_rag_qa.py"
    env = os.environ.copy()
    if body.force_local:
        env["RAG_QA_FORCE_LOCAL"] = "1"
    report_rel = "docs/rag_rerank_comparison.md"
    cmd = [
        sys.executable,
        str(script_path),
        "--strategy",
        strategy,
        "--top-k-before",
        str(body.top_k_before),
        "--top-k-after",
        str(body.top_k_after),
        "--sim-threshold",
        str(body.sim_threshold),
        "--report-path",
        report_rel,
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(_project_root),
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip()
        raise HTTPException(status_code=502, detail=f"RAG benchmark failed: {msg}")
    report_path = _project_root / report_rel
    preview = ""
    if report_path.exists():
        try:
            preview = report_path.read_text(encoding="utf-8", errors="ignore")[:4000]
        except Exception:
            preview = ""
    return {
        "ok": True,
        "stdout": (proc.stdout or "").strip(),
        "report_path": str(report_path),
        "report_preview": preview,
    }


@app.post("/api/rag/mini_chat/turn")
def rag_mini_chat_turn_ep(body: RagMiniChatTurnBody) -> dict[str, Any]:
    q = body.message.strip()
    if not q:
        raise HTTPException(status_code=400, detail="message не может быть пустым")
    strategy = body.strategy.strip().lower()
    if strategy not in ("fixed", "structured", "all"):
        raise HTTPException(status_code=400, detail="strategy должен быть: fixed | structured | all")
    hist: list[dict[str, str]] = []
    for m in body.history:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role", "")).strip()
        content = str(m.get("content", "")).strip()
        if role in ("user", "assistant") and content:
            hist.append({"role": role, "content": content})
    scripts = str(_project_root / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from rag_mini_chat import run_mini_chat_turn

    db_path = _project_root / "rag_index.db"
    try:
        return run_mini_chat_turn(
            q,
            history=hist,
            task_memory=body.task_memory,
            db_path=db_path,
            strategy=strategy,
            top_k_before=body.top_k_before,
            top_k_after=body.top_k_after,
            sim_threshold=body.sim_threshold,
            max_context_chars=body.max_context_chars,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"RAG mini-chat: {_mcp_error_detail(e)}") from e


@app.get("/api/memory-profiles", response_model=list[MemoryProfileOut])
def get_memory_profiles() -> list[MemoryProfileOut]:
    return [
        MemoryProfileOut(
            id=str(p.get("id", "")),
            title=str(p.get("title", "")),
            description=str(p.get("description", "")),
            user_id=str(p.get("id", "")),
        )
        for p in MEMORY_PROFILE_PRESETS
        if str(p.get("id", "")).strip()
    ]


@app.get("/api/chats", response_model=list[ChatOut])
def list_chats(storage: SQLiteChatStorage = Depends(get_storage)) -> list[ChatOut]:
    chats = storage.list_chats(limit=SETTINGS.chat_list_limit)
    return [ChatOut(id=c.chat_id, title=c.title, total_tokens=c.total_tokens) for c in chats]


@app.post("/api/chats", response_model=ChatOut)
def create_chat(
    body: CreateChatBody,
    storage: SQLiteChatStorage = Depends(get_storage),
) -> ChatOut:
    title = (body.title or "").strip()
    if not title:
        title = "Новый чат " + datetime.now().strftime("%Y-%m-%d %H:%M")
    chat_id = storage.create_chat(title=title, system_prompt=SETTINGS.default_system_prompt)
    info = storage.get_chat(chat_id)
    if not info:
        raise HTTPException(status_code=500, detail="Не удалось создать чат")
    return ChatOut(id=info.chat_id, title=info.title, total_tokens=info.total_tokens)


@app.get("/api/chats/{chat_id}/branches", response_model=list[BranchOut])
def list_branches(chat_id: int, storage: SQLiteChatStorage = Depends(get_storage)) -> list[BranchOut]:
    if not storage.get_chat(chat_id):
        raise HTTPException(status_code=404, detail="Чат не найден")
    return [_branch_out(b) for b in storage.list_branches(chat_id)]


@app.patch("/api/chats/{chat_id}/branches/{branch_id}", response_model=BranchOut)
def patch_branch(
    chat_id: int,
    branch_id: int,
    body: PatchBranchBody,
    storage: SQLiteChatStorage = Depends(get_storage),
) -> BranchOut:
    b = storage.get_branch(branch_id)
    if not b or b.chat_id != chat_id:
        raise HTTPException(status_code=404, detail="Ветка не найдена")
    try:
        ms = _normalize_memory_strategy_api(body.memory_strategy)
        pj = _normalize_strategy_params_json(body.strategy_params_json)
        storage.update_branch_settings(
            branch_id,
            title=body.title,
            system_prompt=body.system_prompt,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            timeout_sec=body.timeout_sec,
            memory_strategy=ms,
            strategy_params_json=pj,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    updated = storage.get_branch(branch_id)
    if not updated:
        raise HTTPException(status_code=500, detail="Ошибка обновления")
    return _branch_out(updated)


@app.get("/api/chats/{chat_id}/branches/{branch_id}/facts", response_model=dict[str, str])
def get_branch_facts(
    chat_id: int,
    branch_id: int,
    storage: SQLiteChatStorage = Depends(get_storage),
) -> dict[str, str]:
    if not storage.get_chat(chat_id):
        raise HTTPException(status_code=404, detail="Чат не найден")
    b = storage.get_branch(branch_id)
    if not b or b.chat_id != chat_id:
        raise HTTPException(status_code=404, detail="Ветка не найдена")
    return storage.get_branch_facts_dict(branch_id)


@app.get("/api/chats/{chat_id}/branches/{branch_id}/task-fsm", response_model=TaskFSMOut)
def get_task_fsm(
    chat_id: int,
    branch_id: int,
    storage: SQLiteChatStorage = Depends(get_storage),
) -> TaskFSMOut:
    if not storage.get_chat(chat_id):
        raise HTTPException(status_code=404, detail="Чат не найден")
    b = storage.get_branch(branch_id)
    if not b or b.chat_id != chat_id:
        raise HTTPException(status_code=404, detail="Ветка не найдена")
    return _task_out(get_task_fsm_state(storage, branch_id))


@app.patch("/api/chats/{chat_id}/branches/{branch_id}/task-fsm", response_model=TaskFSMOut)
def patch_task_fsm(
    chat_id: int,
    branch_id: int,
    body: PatchTaskFSMBody,
    storage: SQLiteChatStorage = Depends(get_storage),
) -> TaskFSMOut:
    if not storage.get_chat(chat_id):
        raise HTTPException(status_code=404, detail="Чат не найден")
    b = storage.get_branch(branch_id)
    if not b or b.chat_id != chat_id:
        raise HTTPException(status_code=404, detail="Ветка не найдена")
    try:
        if body.stage is not None:
            state = transition_task_fsm(
                storage,
                branch_id,
                body.stage,
                current_step=body.current_step,
                expected_action=body.expected_action,
            )
        else:
            current = get_task_fsm_state(storage, branch_id)
            state = set_task_fsm_state(
                storage,
                branch_id,
                TaskFSMState(
                    stage=current.stage,
                    current_step=(body.current_step if body.current_step is not None else current.current_step),
                    expected_action=(
                        body.expected_action if body.expected_action is not None else current.expected_action
                    ),
                    previous_stage=current.previous_stage,
                    pause_reason=current.pause_reason,
                ),
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _task_out(state)


@app.post("/api/chats/{chat_id}/branches/{branch_id}/task-fsm/pause", response_model=TaskFSMOut)
def post_task_pause(
    chat_id: int,
    branch_id: int,
    body: PauseTaskBody,
    storage: SQLiteChatStorage = Depends(get_storage),
) -> TaskFSMOut:
    if not storage.get_chat(chat_id):
        raise HTTPException(status_code=404, detail="Чат не найден")
    b = storage.get_branch(branch_id)
    if not b or b.chat_id != chat_id:
        raise HTTPException(status_code=404, detail="Ветка не найдена")
    state = pause_task_fsm(storage, branch_id, body.reason)
    return _task_out(state)


@app.post("/api/chats/{chat_id}/branches/{branch_id}/task-fsm/resume", response_model=TaskFSMOut)
def post_task_resume(
    chat_id: int,
    branch_id: int,
    storage: SQLiteChatStorage = Depends(get_storage),
) -> TaskFSMOut:
    if not storage.get_chat(chat_id):
        raise HTTPException(status_code=404, detail="Чат не найден")
    b = storage.get_branch(branch_id)
    if not b or b.chat_id != chat_id:
        raise HTTPException(status_code=404, detail="Ветка не найдена")
    state = resume_task_fsm(storage, branch_id)
    return _task_out(state)


@app.get(
    "/api/chats/{chat_id}/branches/{branch_id}/working-memory",
    response_model=list[MemoryItemOut],
)
def list_working_memory(
    chat_id: int,
    branch_id: int,
    storage: SQLiteChatStorage = Depends(get_storage),
) -> list[MemoryItemOut]:
    if not storage.get_chat(chat_id):
        raise HTTPException(status_code=404, detail="Чат не найден")
    b = storage.get_branch(branch_id)
    if not b or b.chat_id != chat_id:
        raise HTTPException(status_code=404, detail="Ветка не найдена")
    return [
        MemoryItemOut(key=r.key, value=r.value, updated_at=r.updated_at)
        for r in storage.list_working_memory(branch_id)
    ]


@app.put(
    "/api/chats/{chat_id}/branches/{branch_id}/working-memory/{mem_key}",
    response_model=MemoryItemOut,
)
def put_working_memory_item(
    chat_id: int,
    branch_id: int,
    mem_key: str,
    body: PutMemoryBody,
    storage: SQLiteChatStorage = Depends(get_storage),
) -> MemoryItemOut:
    if not mem_key.strip():
        raise HTTPException(status_code=400, detail="Пустой ключ")
    if not storage.get_chat(chat_id):
        raise HTTPException(status_code=404, detail="Чат не найден")
    b = storage.get_branch(branch_id)
    if not b or b.chat_id != chat_id:
        raise HTTPException(status_code=404, detail="Ветка не найдена")
    storage.upsert_working_memory(branch_id, mem_key.strip(), body.value)
    for r in storage.list_working_memory(branch_id):
        if r.key == mem_key.strip():
            return MemoryItemOut(key=r.key, value=r.value, updated_at=r.updated_at)
    raise HTTPException(status_code=500, detail="Не удалось сохранить рабочую память")


@app.delete("/api/chats/{chat_id}/branches/{branch_id}/working-memory/{mem_key}")
def delete_working_memory_item(
    chat_id: int,
    branch_id: int,
    mem_key: str,
    storage: SQLiteChatStorage = Depends(get_storage),
) -> dict[str, bool]:
    if not storage.get_chat(chat_id):
        raise HTTPException(status_code=404, detail="Чат не найден")
    b = storage.get_branch(branch_id)
    if not b or b.chat_id != chat_id:
        raise HTTPException(status_code=404, detail="Ветка не найдена")
    deleted = storage.delete_working_memory(branch_id, mem_key.strip())
    return {"deleted": deleted}


@app.delete("/api/chats/{chat_id}/branches/{branch_id}/working-memory")
def clear_working_memory(
    chat_id: int,
    branch_id: int,
    storage: SQLiteChatStorage = Depends(get_storage),
) -> dict[str, bool]:
    if not storage.get_chat(chat_id):
        raise HTTPException(status_code=404, detail="Чат не найден")
    b = storage.get_branch(branch_id)
    if not b or b.chat_id != chat_id:
        raise HTTPException(status_code=404, detail="Ветка не найдена")
    storage.clear_working_memory(branch_id)
    return {"ok": True}


@app.get("/api/users/{user_id}/long-term-memory", response_model=list[MemoryItemOut])
def list_long_term_memory(
    user_id: str,
    storage: SQLiteChatStorage = Depends(get_storage),
) -> list[MemoryItemOut]:
    uid = user_id.strip()
    if not uid:
        raise HTTPException(status_code=400, detail="Пустой user_id")
    return [
        MemoryItemOut(key=r.key, value=r.value, updated_at=r.updated_at)
        for r in storage.list_long_term_memory(uid)
    ]


@app.put("/api/users/{user_id}/long-term-memory/{mem_key}", response_model=MemoryItemOut)
def put_long_term_memory_item(
    user_id: str,
    mem_key: str,
    body: PutMemoryBody,
    storage: SQLiteChatStorage = Depends(get_storage),
) -> MemoryItemOut:
    uid = user_id.strip()
    key = mem_key.strip()
    if not uid:
        raise HTTPException(status_code=400, detail="Пустой user_id")
    if not key:
        raise HTTPException(status_code=400, detail="Пустой ключ")
    storage.upsert_long_term_memory(uid, key, body.value)
    for r in storage.list_long_term_memory(uid):
        if r.key == key:
            return MemoryItemOut(key=r.key, value=r.value, updated_at=r.updated_at)
    raise HTTPException(status_code=500, detail="Не удалось сохранить долговременную память")


@app.delete("/api/users/{user_id}/long-term-memory/{mem_key}")
def delete_long_term_memory_item(
    user_id: str,
    mem_key: str,
    storage: SQLiteChatStorage = Depends(get_storage),
) -> dict[str, bool]:
    uid = user_id.strip()
    key = mem_key.strip()
    if not uid:
        raise HTTPException(status_code=400, detail="Пустой user_id")
    if not key:
        raise HTTPException(status_code=400, detail="Пустой ключ")
    deleted = storage.delete_long_term_memory(uid, key)
    return {"deleted": deleted}


@app.delete("/api/users/{user_id}/long-term-memory")
def clear_long_term_memory(
    user_id: str,
    storage: SQLiteChatStorage = Depends(get_storage),
) -> dict[str, bool]:
    uid = user_id.strip()
    if not uid:
        raise HTTPException(status_code=400, detail="Пустой user_id")
    storage.clear_long_term_memory(uid)
    return {"ok": True}


@app.get("/api/users/{user_id}/invariants", response_model=list[InvariantOut])
def list_invariants_api(
    user_id: str,
    storage: SQLiteChatStorage = Depends(get_storage),
) -> list[InvariantOut]:
    uid = user_id.strip()
    if not uid:
        raise HTTPException(status_code=400, detail="Пустой user_id")
    rows = storage.list_invariants(uid, active_only=True)
    return [_invariant_out(r) for r in rows]


@app.post("/api/users/{user_id}/invariants", response_model=InvariantOut)
def create_invariant_api(
    user_id: str,
    body: InvariantCreateBody,
    storage: SQLiteChatStorage = Depends(get_storage),
) -> InvariantOut:
    uid = user_id.strip()
    if not uid:
        raise HTTPException(status_code=400, detail="Пустой user_id")
    try:
        cat = _normalize_invariant_category(body.category)
        sev = _normalize_invariant_severity(body.severity)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    title = body.title.strip()
    statement = body.statement.strip()
    if not title or not statement:
        raise HTTPException(status_code=400, detail="Заполните title и statement")
    iid = storage.create_invariant(uid, category=cat, severity=sev, title=title, statement=statement)
    r = storage.get_invariant(uid, iid)
    if not r:
        raise HTTPException(status_code=500, detail="Не удалось создать инвариант")
    return _invariant_out(r)


@app.patch("/api/users/{user_id}/invariants/{invariant_id}", response_model=InvariantOut)
def patch_invariant_api(
    user_id: str,
    invariant_id: int,
    body: InvariantPatchBody,
    storage: SQLiteChatStorage = Depends(get_storage),
) -> InvariantOut:
    uid = user_id.strip()
    if not uid:
        raise HTTPException(status_code=400, detail="Пустой user_id")
    try:
        cat = _normalize_invariant_category(body.category) if body.category is not None else None
        sev = _normalize_invariant_severity(body.severity) if body.severity is not None else None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    title = body.title.strip() if body.title is not None else None
    statement = body.statement.strip() if body.statement is not None else None
    if title is not None and not title:
        raise HTTPException(status_code=400, detail="Пустой title")
    if statement is not None and not statement:
        raise HTTPException(status_code=400, detail="Пустой statement")
    active_i: int | None = None
    if body.active is not None:
        active_i = 1 if body.active else 0
    storage.update_invariant(
        uid,
        invariant_id,
        category=cat,
        severity=sev,
        title=title,
        statement=statement,
        active=active_i,
    )
    r = storage.get_invariant(uid, invariant_id)
    if not r:
        raise HTTPException(status_code=404, detail="Инвариант не найден")
    return _invariant_out(r)


@app.delete("/api/users/{user_id}/invariants/{invariant_id}")
def delete_invariant_api(
    user_id: str,
    invariant_id: int,
    storage: SQLiteChatStorage = Depends(get_storage),
) -> dict[str, bool]:
    uid = user_id.strip()
    if not uid:
        raise HTTPException(status_code=400, detail="Пустой user_id")
    deleted = storage.delete_invariant(uid, invariant_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Инвариант не найден")
    return {"deleted": True}


@app.post("/api/chats/{chat_id}/branches/{parent_branch_id}/fork", response_model=BranchOut)
def fork_branch(
    chat_id: int,
    parent_branch_id: int,
    body: ForkBody,
    storage: SQLiteChatStorage = Depends(get_storage),
) -> BranchOut:
    if not storage.get_chat(chat_id):
        raise HTTPException(status_code=404, detail="Чат не найден")
    parent = storage.get_branch(parent_branch_id)
    if not parent or parent.chat_id != chat_id:
        raise HTTPException(status_code=404, detail="Родительская ветка не найдена")

    sp = body.system_prompt if body.system_prompt is not None else parent.system_prompt
    temp = body.temperature if body.temperature is not None else parent.temperature
    mt = body.max_tokens if body.max_tokens is not None else parent.max_tokens
    to = body.timeout_sec if body.timeout_sec is not None else parent.timeout_sec

    try:
        new_id = storage.fork_branch(
            chat_id=chat_id,
            parent_branch_id=parent_branch_id,
            fork_after_message_id=body.fork_after_message_id,
            title=body.title.strip() or "Новая ветка",
            system_prompt=sp,
            temperature=temp,
            max_tokens=mt,
            timeout_sec=to,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    nb = storage.get_branch(new_id)
    if not nb:
        raise HTTPException(status_code=500, detail="Не удалось создать ветку")
    return _branch_out(nb)


@app.get("/api/chats/{chat_id}/branches/{branch_id}/messages", response_model=list[MessageOut])
def get_branch_messages(
    chat_id: int,
    branch_id: int,
    storage: SQLiteChatStorage = Depends(get_storage),
) -> list[MessageOut]:
    if not storage.get_chat(chat_id):
        raise HTTPException(status_code=404, detail="Чат не найден")
    b = storage.get_branch(branch_id)
    if not b or b.chat_id != chat_id:
        raise HTTPException(status_code=404, detail="Ветка не найдена")
    rows = storage.list_messages_all(chat_id, branch_id)
    return [
        MessageOut(
            id=r.message_id,
            role=r.role,
            content=r.content,
            summarized=bool(r.is_summarized),
        )
        for r in rows
    ]


@app.post("/api/chats/{chat_id}/branches/{branch_id}/messages", response_model=SendMessageResponse)
def post_branch_message(
    chat_id: int,
    branch_id: int,
    body: SendMessageBody,
    storage: SQLiteChatStorage = Depends(get_storage),
) -> SendMessageResponse:
    if not storage.get_chat(chat_id):
        raise HTTPException(status_code=404, detail="Чат не найден")
    b = storage.get_branch(branch_id)
    if not b or b.chat_id != chat_id:
        raise HTTPException(status_code=404, detail="Ветка не найдена")
    try:
        result = send_message(storage, chat_id, branch_id, body.content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return SendMessageResponse(
        assistant_text=result.assistant_text,
        model=result.model,
        tokens_this_turn=result.tokens_this_turn,
        total_tokens_branch=result.total_tokens_branch,
        total_tokens_chat=result.total_tokens_chat,
        elapsed_sec=result.elapsed_sec,
    )


@app.post("/api/chats/{chat_id}/branches/{branch_id}/messages/stream")
def post_branch_message_stream(
    chat_id: int,
    branch_id: int,
    body: SendMessageBody,
    storage: SQLiteChatStorage = Depends(get_storage),
) -> StreamingResponse:
    if not storage.get_chat(chat_id):
        raise HTTPException(status_code=404, detail="Чат не найден")
    b = storage.get_branch(branch_id)
    if not b or b.chat_id != chat_id:
        raise HTTPException(status_code=404, detail="Ветка не найдена")
    key = (chat_id, branch_id)
    stop_event = threading.Event()
    with _stream_stop_lock:
        _stream_stops[key] = stop_event

    def event_iter():
        try:
            for ev in send_message_stream(
                storage,
                chat_id,
                branch_id,
                body.content,
                should_stop=lambda: stop_event.is_set(),
            ):
                if ev.get("type") == "delta":
                    yield _sse("delta", {"delta": str(ev.get("delta", ""))})
                elif ev.get("type") == "status":
                    yield _sse(
                        "status",
                        {
                            "phase": str(ev.get("phase", "")),
                            "message": str(ev.get("message", "")),
                        },
                    )
                elif ev.get("type") == "stopped":
                    yield _sse("stopped", {"stopped": bool(ev.get("stopped"))})
                elif ev.get("type") == "done":
                    r = ev.get("result")
                    if r is None:
                        continue
                    yield _sse(
                        "done",
                        {
                            "assistant_text": r.assistant_text,
                            "model": r.model,
                            "tokens_this_turn": r.tokens_this_turn,
                            "total_tokens_branch": r.total_tokens_branch,
                            "total_tokens_chat": r.total_tokens_chat,
                            "elapsed_sec": r.elapsed_sec,
                        },
                    )
        except ValueError as e:
            yield _sse("error", {"message": str(e)})
        except Exception as e:
            yield _sse("error", {"message": f"stream_failed: {e}"})
        finally:
            with _stream_stop_lock:
                if _stream_stops.get(key) is stop_event:
                    _stream_stops.pop(key, None)

    return StreamingResponse(event_iter(), media_type="text/event-stream")


@app.post("/api/chats/{chat_id}/branches/{branch_id}/messages/resume-stream")
def post_branch_message_resume_stream(
    chat_id: int,
    branch_id: int,
    storage: SQLiteChatStorage = Depends(get_storage),
) -> StreamingResponse:
    if not storage.get_chat(chat_id):
        raise HTTPException(status_code=404, detail="Чат не найден")
    b = storage.get_branch(branch_id)
    if not b or b.chat_id != chat_id:
        raise HTTPException(status_code=404, detail="Ветка не найдена")
    key = (chat_id, branch_id)
    stop_event = threading.Event()
    with _stream_stop_lock:
        _stream_stops[key] = stop_event

    def event_iter():
        try:
            for ev in resume_last_answer_stream(
                storage,
                chat_id,
                branch_id,
                should_stop=lambda: stop_event.is_set(),
            ):
                if ev.get("type") == "delta":
                    yield _sse("delta", {"delta": str(ev.get("delta", ""))})
                elif ev.get("type") == "status":
                    yield _sse(
                        "status",
                        {
                            "phase": str(ev.get("phase", "")),
                            "message": str(ev.get("message", "")),
                        },
                    )
                elif ev.get("type") == "stopped":
                    yield _sse("stopped", {"stopped": bool(ev.get("stopped"))})
                elif ev.get("type") == "done":
                    r = ev.get("result")
                    if r is None:
                        continue
                    yield _sse(
                        "done",
                        {
                            "assistant_text": r.assistant_text,
                            "model": r.model,
                            "tokens_this_turn": r.tokens_this_turn,
                            "total_tokens_branch": r.total_tokens_branch,
                            "total_tokens_chat": r.total_tokens_chat,
                            "elapsed_sec": r.elapsed_sec,
                        },
                    )
        except ValueError as e:
            yield _sse("error", {"message": str(e)})
        except Exception as e:
            yield _sse("error", {"message": f"resume_stream_failed: {e}"})
        finally:
            with _stream_stop_lock:
                if _stream_stops.get(key) is stop_event:
                    _stream_stops.pop(key, None)

    return StreamingResponse(event_iter(), media_type="text/event-stream")


@app.post("/api/chats/{chat_id}/branches/{branch_id}/messages/stop")
def post_branch_message_stop(chat_id: int, branch_id: int) -> dict[str, bool]:
    key = (chat_id, branch_id)
    with _stream_stop_lock:
        ev = _stream_stops.get(key)
    if ev is None:
        return {"ok": False, "found": False}
    ev.set()
    return {"ok": True, "found": True}


@app.post("/api/chats/{chat_id}/branches/{branch_id}/messages/stop-and-pause", response_model=TaskFSMOut)
def post_branch_message_stop_and_pause(
    chat_id: int,
    branch_id: int,
    body: PauseTaskBody,
    storage: SQLiteChatStorage = Depends(get_storage),
) -> TaskFSMOut:
    if not storage.get_chat(chat_id):
        raise HTTPException(status_code=404, detail="Чат не найден")
    b = storage.get_branch(branch_id)
    if not b or b.chat_id != chat_id:
        raise HTTPException(status_code=404, detail="Ветка не найдена")
    key = (chat_id, branch_id)
    with _stream_stop_lock:
        ev = _stream_stops.get(key)
    if ev is not None:
        ev.set()
    state = pause_task_fsm(storage, branch_id, body.reason)
    return _task_out(state)


@app.get("/api/chats/{chat_id}/messages", response_model=list[MessageOut])
def get_messages_legacy(
    chat_id: int,
    storage: SQLiteChatStorage = Depends(get_storage),
) -> list[MessageOut]:
    if not storage.get_chat(chat_id):
        raise HTTPException(status_code=404, detail="Чат не найден")
    bid = storage.get_main_branch_id(chat_id)
    if bid is None:
        raise HTTPException(status_code=404, detail="Нет основной ветки")
    rows = storage.list_messages_all(chat_id, bid)
    return [
        MessageOut(
            id=r.message_id,
            role=r.role,
            content=r.content,
            summarized=bool(r.is_summarized),
        )
        for r in rows
    ]


@app.post("/api/chats/{chat_id}/messages", response_model=SendMessageResponse)
def post_message_legacy(
    chat_id: int,
    body: SendMessageBody,
    storage: SQLiteChatStorage = Depends(get_storage),
) -> SendMessageResponse:
    if not storage.get_chat(chat_id):
        raise HTTPException(status_code=404, detail="Чат не найден")
    bid = storage.get_main_branch_id(chat_id)
    if bid is None:
        raise HTTPException(status_code=404, detail="Нет основной ветки")
    try:
        result = send_message(storage, chat_id, bid, body.content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return SendMessageResponse(
        assistant_text=result.assistant_text,
        model=result.model,
        tokens_this_turn=result.tokens_this_turn,
        total_tokens_branch=result.total_tokens_branch,
        total_tokens_chat=result.total_tokens_chat,
        elapsed_sec=result.elapsed_sec,
    )
