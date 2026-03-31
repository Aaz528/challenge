from __future__ import annotations

import json
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app_settings import MEMORY_PROFILE_PRESETS, MEMORY_STRATEGIES, SETTINGS, WEB_SETTINGS
from chat_service import send_message
from sqlite_chat_storage import BranchInfo, SQLiteChatStorage

from api.deps import get_storage

app = FastAPI(title="LLM Agent API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(WEB_SETTINGS.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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
