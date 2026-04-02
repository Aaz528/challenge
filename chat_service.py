from __future__ import annotations

import json
from dataclasses import dataclass

from app_settings import (
    MEMORY_DEFAULTS,
    MEMORY_STRATEGIES,
    MEMORY_STRATEGY_DEFAULT,
    MEMORY_STRATEGY_SLIDING,
    MEMORY_STRATEGY_STICKY,
    MEMORY_STRATEGY_SUMMARY,
    MEMORY_STRATEGY_TRIPLE,
    SETTINGS,
    SUMMARY_SETTINGS,
)
from llm_agent import LLMAgent, LLMConfig, ToolCallSpec
from sqlite_chat_storage import BranchInfo, SQLiteChatStorage


@dataclass(frozen=True)
class SendMessageResult:
    assistant_text: str
    model: str
    tokens_this_turn: int | None
    total_tokens_branch: int
    total_tokens_chat: int
    elapsed_sec: float


TASK_FSM_KEY = "task_fsm"
TASK_STAGE_PLANNING = "planning"
TASK_STAGE_EXECUTION = "execution"
TASK_STAGE_VALIDATION = "validation"
TASK_STAGE_DONE = "done"
TASK_STAGE_PAUSED = "paused"
TASK_STAGES = (
    TASK_STAGE_PLANNING,
    TASK_STAGE_EXECUTION,
    TASK_STAGE_VALIDATION,
    TASK_STAGE_DONE,
    TASK_STAGE_PAUSED,
)

TASK_STAGE_TRANSITIONS: dict[str, tuple[str, ...]] = {
    TASK_STAGE_PLANNING: (TASK_STAGE_EXECUTION, TASK_STAGE_PAUSED),
    TASK_STAGE_EXECUTION: (TASK_STAGE_VALIDATION, TASK_STAGE_PAUSED),
    TASK_STAGE_VALIDATION: (TASK_STAGE_DONE, TASK_STAGE_PAUSED),
    TASK_STAGE_DONE: tuple(),
    TASK_STAGE_PAUSED: tuple(),  # handled via resume (previous stage)
}


@dataclass(frozen=True)
class TaskFSMState:
    stage: str
    current_step: str
    expected_action: str
    previous_stage: str | None = None
    pause_reason: str | None = None


def normalize_memory_strategy(raw: str | None) -> str:
    s = (raw or MEMORY_STRATEGY_SUMMARY).strip().lower()
    if s not in MEMORY_STRATEGIES:
        return MEMORY_STRATEGY_SUMMARY
    return s


def parse_strategy_params(branch: BranchInfo) -> dict:
    try:
        return json.loads(branch.strategy_params_json or "{}")
    except json.JSONDecodeError:
        return {}


def user_id_for_invariants(branch: BranchInfo, params: dict | None = None) -> str:
    p = params if params is not None else parse_strategy_params(branch)
    uid = str(p.get("user_id", MEMORY_DEFAULTS.triple_default_user_id)).strip()
    return uid if uid else MEMORY_DEFAULTS.triple_default_user_id


def apply_invariants_to_context(
    storage: SQLiteChatStorage,
    branch_id: int,
    messages: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Вставляет system-блок с инвариантами сразу после первого system-сообщения (обычно prompt ветки)."""
    b = storage.get_branch(branch_id)
    if not b:
        return messages
    uid = user_id_for_invariants(b)
    rows = storage.list_invariants(uid, active_only=True)
    if not rows:
        return messages
    lines = [
        f"Инварианты пользователя (user_id={uid}), хранятся отдельно от диалога. "
        "Учитывай их в рассуждениях и в финальном ответе.",
        'Инварианты с severity "hard" нельзя нарушать: если запрос пользователя требует их нарушения — '
        "не выполняй его в таком виде; кратко объясни конфликт и предложи допустимую альтернативу или уточняющие вопросы.",
        'Инварианты с severity "soft" желательно соблюдать; если нельзя — явно укажи конфликт.',
        "",
    ]
    for r in rows:
        lines.append(f"- [{r.category}] ({r.severity}) {r.title}: {r.statement}")
    inv_msg: dict[str, str] = {"role": "system", "content": "\n".join(lines)}
    if not messages:
        return [inv_msg]
    if messages[0].get("role") == "system":
        return [messages[0], inv_msg, *messages[1:]]
    return [inv_msg, *messages]


def _ua_rows(storage: SQLiteChatStorage, chat_id: int, branch_id: int):
    return [
        r
        for r in storage.list_messages_all(chat_id, branch_id)
        if r.role in ("user", "assistant")
    ]


def build_context_default(storage: SQLiteChatStorage, branch_id: int) -> list[dict[str, str]]:
    b = storage.get_branch(branch_id)
    if not b:
        return []
    rows = _ua_rows(storage, b.chat_id, branch_id)
    out: list[dict[str, str]] = [{"role": "system", "content": b.system_prompt}]
    for r in rows:
        out.append({"role": r.role, "content": r.content})
    return apply_invariants_to_context(storage, branch_id, out)


def build_context_sliding(
    storage: SQLiteChatStorage, chat_id: int, branch_id: int, params: dict
) -> list[dict[str, str]]:
    b = storage.get_branch(branch_id)
    if not b:
        return []
    wm = int(params.get("sliding_window_messages", MEMORY_DEFAULTS.sliding_window_messages))
    rows = _ua_rows(storage, chat_id, branch_id)
    if wm <= 1:
        tail = []
    else:
        take = max(wm - 1, 0)
        tail = rows[-take:] if take else []
    out: list[dict[str, str]] = [{"role": "system", "content": b.system_prompt}]
    for r in tail:
        out.append({"role": r.role, "content": r.content})
    return apply_invariants_to_context(storage, branch_id, out)


def refresh_sticky_facts(
    storage: SQLiteChatStorage, agent: LLMAgent, chat_id: int, branch_id: int, params: dict
) -> tuple[int | None, float]:
    """После записи user-сообщения. Возвращает (tokens, elapsed) от вызова merge."""
    tail_n = max(int(params.get("sticky_tail_messages", MEMORY_DEFAULTS.sticky_tail_messages)), 8)
    rows = _ua_rows(storage, chat_id, branch_id)
    snippet = "\n".join(f"{r.role.upper()}: {r.content}" for r in rows[-tail_n:])
    existing = storage.get_branch_facts_dict(branch_id)
    merged, merge_res = agent.merge_sticky_facts(existing, snippet)
    storage.replace_branch_facts(branch_id, merged)
    tok = merge_res.usage.total_tokens
    return tok, merge_res.elapsed_sec


def build_sticky_context_after_user(
    storage: SQLiteChatStorage, chat_id: int, branch_id: int, params: dict
) -> list[dict[str, str]]:
    b = storage.get_branch(branch_id)
    if not b:
        return []
    facts = storage.get_branch_facts_dict(branch_id)
    tail_n = int(params.get("sticky_tail_messages", MEMORY_DEFAULTS.sticky_tail_messages))
    rows = _ua_rows(storage, chat_id, branch_id)
    tail = rows[-tail_n:] if tail_n > 0 else rows
    out: list[dict[str, str]] = [
        {"role": "system", "content": b.system_prompt},
        {
            "role": "system",
            "content": "Известные факты (ключ-значение, JSON):\n"
            + json.dumps(facts, ensure_ascii=False, indent=2),
        },
    ]
    for r in tail:
        out.append({"role": r.role, "content": r.content})
    return apply_invariants_to_context(storage, branch_id, out)


def _stringify_kv(rows) -> str:
    if not rows:
        return "{}"
    data = {r.key: r.value for r in rows}
    return json.dumps(data, ensure_ascii=False, indent=2)


def _task_fsm_to_json(state: TaskFSMState) -> str:
    payload: dict[str, str] = {
        "stage": state.stage,
        "current_step": state.current_step,
        "expected_action": state.expected_action,
    }
    if state.previous_stage:
        payload["previous_stage"] = state.previous_stage
    if state.pause_reason:
        payload["pause_reason"] = state.pause_reason
    return json.dumps(payload, ensure_ascii=False)


def _parse_task_fsm(raw: str | None) -> TaskFSMState | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    stage = str(data.get("stage", "")).strip().lower()
    if stage not in TASK_STAGES:
        return None
    current_step = str(data.get("current_step", "")).strip()
    expected_action = str(data.get("expected_action", "")).strip()
    prev = str(data.get("previous_stage", "")).strip().lower() or None
    if prev and prev not in TASK_STAGES:
        prev = None
    pause_reason = str(data.get("pause_reason", "")).strip() or None
    return TaskFSMState(
        stage=stage,
        current_step=current_step,
        expected_action=expected_action,
        previous_stage=prev,
        pause_reason=pause_reason,
    )


def get_task_fsm_state(storage: SQLiteChatStorage, branch_id: int) -> TaskFSMState:
    wm = storage.get_working_memory_dict(branch_id)
    parsed = _parse_task_fsm(wm.get(TASK_FSM_KEY))
    if parsed:
        return parsed
    return TaskFSMState(
        stage=TASK_STAGE_PLANNING,
        current_step="Сформировать план",
        expected_action="Уточнить требования и подтвердить план",
    )


def set_task_fsm_state(storage: SQLiteChatStorage, branch_id: int, state: TaskFSMState) -> TaskFSMState:
    if state.stage not in TASK_STAGES:
        raise ValueError(f"Неизвестный этап: {state.stage}")
    storage.upsert_working_memory(branch_id, TASK_FSM_KEY, _task_fsm_to_json(state))
    return state


def transition_task_fsm(
    storage: SQLiteChatStorage,
    branch_id: int,
    target_stage: str,
    *,
    current_step: str | None = None,
    expected_action: str | None = None,
) -> TaskFSMState:
    state = get_task_fsm_state(storage, branch_id)
    dst = (target_stage or "").strip().lower()
    if dst not in TASK_STAGES:
        raise ValueError(f"Неизвестный этап: {target_stage}")
    if dst == TASK_STAGE_PAUSED:
        raise ValueError("Для паузы используйте pause_task_fsm().")
    if state.stage == TASK_STAGE_PAUSED:
        raise ValueError("Нельзя менять этап из paused напрямую, используйте resume_task_fsm().")
    allowed = TASK_STAGE_TRANSITIONS.get(state.stage, tuple())
    if dst != state.stage and dst not in allowed:
        raise ValueError(f"Переход {state.stage} -> {dst} запрещен.")
    next_state = TaskFSMState(
        stage=dst,
        current_step=(current_step if current_step is not None else state.current_step).strip(),
        expected_action=(expected_action if expected_action is not None else state.expected_action).strip(),
    )
    return set_task_fsm_state(storage, branch_id, next_state)


def pause_task_fsm(storage: SQLiteChatStorage, branch_id: int, reason: str | None = None) -> TaskFSMState:
    state = get_task_fsm_state(storage, branch_id)
    if state.stage == TASK_STAGE_PAUSED:
        return state
    paused = TaskFSMState(
        stage=TASK_STAGE_PAUSED,
        current_step=state.current_step,
        expected_action=state.expected_action,
        previous_stage=state.stage,
        pause_reason=(reason or "").strip() or None,
    )
    return set_task_fsm_state(storage, branch_id, paused)


def resume_task_fsm(storage: SQLiteChatStorage, branch_id: int) -> TaskFSMState:
    state = get_task_fsm_state(storage, branch_id)
    if state.stage != TASK_STAGE_PAUSED:
        return state
    prev = state.previous_stage or TASK_STAGE_EXECUTION
    if prev not in TASK_STAGES or prev == TASK_STAGE_PAUSED:
        prev = TASK_STAGE_EXECUTION
    resumed = TaskFSMState(
        stage=prev,
        current_step=state.current_step,
        expected_action=state.expected_action,
        previous_stage=None,
        pause_reason=None,
    )
    return set_task_fsm_state(storage, branch_id, resumed)


def build_triple_context(
    storage: SQLiteChatStorage, chat_id: int, branch_id: int, params: dict
) -> list[dict[str, str]]:
    b = storage.get_branch(branch_id)
    if not b:
        return []

    user_id = str(params.get("user_id", MEMORY_DEFAULTS.triple_default_user_id)).strip()
    if not user_id:
        user_id = MEMORY_DEFAULTS.triple_default_user_id
    tail_n = int(params.get("triple_short_tail_messages", MEMORY_DEFAULTS.triple_short_tail_messages))
    rows = _ua_rows(storage, chat_id, branch_id)
    tail = rows[-tail_n:] if tail_n > 0 else rows
    wm = storage.list_working_memory(branch_id)
    lm = storage.list_long_term_memory(user_id)

    out: list[dict[str, str]] = [
        {"role": "system", "content": b.system_prompt},
        {
            "role": "system",
            "content": (
                "Рабочая память (текущая задача, можно изменять через tools):\n"
                + _stringify_kv(wm)
            ),
        },
        {
            "role": "system",
            "content": (
                f"Долговременная память пользователя user_id={user_id} (только для чтения):\n"
                + _stringify_kv(lm)
            ),
        },
    ]
    for r in tail:
        out.append({"role": r.role, "content": r.content})
    return apply_invariants_to_context(storage, branch_id, out)


def refresh_working_memory_auto(
    storage: SQLiteChatStorage, agent: LLMAgent, chat_id: int, branch_id: int, params: dict
) -> tuple[int | None, float]:
    """После записи user-сообщения. Автообновляет working memory и возвращает (tokens, elapsed)."""
    tail_n = max(int(params.get("triple_short_tail_messages", MEMORY_DEFAULTS.triple_short_tail_messages)), 6)
    rows = _ua_rows(storage, chat_id, branch_id)
    snippet = "\n".join(f"{r.role.upper()}: {r.content}" for r in rows[-tail_n:])
    existing = storage.get_working_memory_dict(branch_id)
    merged, merge_res = agent.merge_working_memory(existing, snippet)
    storage.replace_working_memory(branch_id, merged)
    return merge_res.usage.total_tokens, merge_res.elapsed_sec


def _working_memory_tools() -> list[ToolCallSpec]:
    return [
        ToolCallSpec(
            name="wm_list_items",
            description="Получить текущие данные рабочей памяти задачи.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        ToolCallSpec(
            name="wm_set_item",
            description="Создать/обновить запись рабочей памяти по ключу.",
            parameters={
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "value": {"type": "string"},
                },
                "required": ["key", "value"],
                "additionalProperties": False,
            },
        ),
        ToolCallSpec(
            name="wm_delete_item",
            description="Удалить запись рабочей памяти по ключу.",
            parameters={
                "type": "object",
                "properties": {"key": {"type": "string"}},
                "required": ["key"],
                "additionalProperties": False,
            },
        ),
        ToolCallSpec(
            name="wm_clear",
            description="Очистить всю рабочую память текущей ветки.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
        ),
    ]


def _execute_working_memory_tool(
    storage: SQLiteChatStorage, branch_id: int, tool_name: str, args: dict
) -> dict:
    if tool_name == "wm_list_items":
        return {"items": {r.key: r.value for r in storage.list_working_memory(branch_id)}}
    if tool_name == "wm_set_item":
        key = str(args.get("key", "")).strip()
        if not key:
            return {"ok": False, "error": "key обязателен"}
        value = str(args.get("value", ""))
        storage.upsert_working_memory(branch_id, key, value)
        return {"ok": True}
    if tool_name == "wm_delete_item":
        key = str(args.get("key", "")).strip()
        if not key:
            return {"ok": False, "error": "key обязателен"}
        deleted = storage.delete_working_memory(branch_id, key)
        return {"ok": True, "deleted": deleted}
    if tool_name == "wm_clear":
        storage.clear_working_memory(branch_id)
        return {"ok": True}
    return {"ok": False, "error": f"неизвестный tool: {tool_name}"}


def build_unsummarized_turns(
    storage: SQLiteChatStorage, branch_id: int
) -> list[tuple[int, int, list[dict[str, str]]]]:
    rows = [r for r in storage.get_unsummarized_message_rows(branch_id) if r.is_summarized == 0]
    turns: list[tuple[int, int, list[dict[str, str]]]] = []
    i = 0
    while i + 1 < len(rows):
        r1 = rows[i]
        r2 = rows[i + 1]
        if r1.role == "user" and r2.role == "assistant":
            turns.append(
                (
                    r1.message_id,
                    r2.message_id,
                    [
                        {"role": "user", "content": r1.content},
                        {"role": "assistant", "content": r2.content},
                    ],
                )
            )
            i += 2
            continue
        i += 1
    return turns


def maybe_rollup_summaries(storage: SQLiteChatStorage, agent: LLMAgent, branch_id: int) -> None:
    while True:
        turns = build_unsummarized_turns(storage, branch_id)
        if len(turns) < SUMMARY_SETTINGS.min_turns_to_rollup:
            return
        candidate = turns[: -SUMMARY_SETTINGS.keep_last_turns]
        if len(candidate) < SUMMARY_SETTINGS.rollup_turns_per_batch:
            return

        block = candidate[-SUMMARY_SETTINGS.rollup_turns_per_batch :]
        flat_messages: list[dict[str, str]] = []
        for _, _, turn_messages in block:
            flat_messages.extend(turn_messages)

        summary_text = agent.summarize_messages(flat_messages)
        from_id = block[0][0]
        to_id = block[-1][1]
        storage.create_summary_and_mark(
            branch_id=branch_id,
            summary_text=summary_text,
            from_message_id=from_id,
            to_message_id=to_id,
        )


def create_agent_for_branch(storage: SQLiteChatStorage, branch_id: int) -> LLMAgent:
    b = storage.get_branch(branch_id)
    if not b:
        raise ValueError("Ветка не найдена")
    config = LLMConfig.from_env()
    return LLMAgent(
        config,
        system_prompt=b.system_prompt,
        timeout_sec=b.timeout_sec,
        temperature=b.temperature,
        max_tokens=b.max_tokens,
    )


def send_message(
    storage: SQLiteChatStorage,
    chat_id: int,
    branch_id: int,
    user_text: str,
) -> SendMessageResult:
    user_text = (user_text or "").strip()
    if not user_text:
        raise ValueError("Пустое сообщение")

    chat = storage.get_chat(chat_id)
    if not chat:
        raise ValueError("Чат не найден")

    branch = storage.get_branch(branch_id)
    if not branch or branch.chat_id != chat_id:
        raise ValueError("Ветка не найдена")

    strategy = normalize_memory_strategy(branch.memory_strategy)
    params = parse_strategy_params(branch)
    agent = create_agent_for_branch(storage, branch_id)

    tokens_merge: int | None = None
    elapsed_merge = 0.0

    if strategy == MEMORY_STRATEGY_STICKY:
        storage.append_message(chat_id, branch_id, "user", user_text)
        tok_m, el_m = refresh_sticky_facts(storage, agent, chat_id, branch_id, params)
        tokens_merge = tok_m
        elapsed_merge = el_m
        ctx = build_sticky_context_after_user(storage, chat_id, branch_id, params)
        result = agent.complete_messages(ctx)
        storage.append_message(chat_id, branch_id, "assistant", result.text)
        total_llm_tokens = 0
        if tokens_merge is not None:
            total_llm_tokens += tokens_merge
        if result.usage.total_tokens is not None:
            total_llm_tokens += result.usage.total_tokens
        if total_llm_tokens > 0:
            storage.add_tokens(chat_id, branch_id, total_llm_tokens)
        tok_display = total_llm_tokens if total_llm_tokens > 0 else result.usage.total_tokens
        elapsed = elapsed_merge + result.elapsed_sec
    elif strategy == MEMORY_STRATEGY_DEFAULT:
        ctx = build_context_default(storage, branch_id)
        result = agent.chat_turn_with_messages(ctx, user_text)
        storage.append_message(chat_id, branch_id, "user", user_text)
        storage.append_message(chat_id, branch_id, "assistant", result.text)
        if result.usage.total_tokens is not None:
            storage.add_tokens(chat_id, branch_id, result.usage.total_tokens)
        tok_display = result.usage.total_tokens
        elapsed = result.elapsed_sec
    elif strategy == MEMORY_STRATEGY_SLIDING:
        ctx = build_context_sliding(storage, chat_id, branch_id, params)
        result = agent.chat_turn_with_messages(ctx, user_text)
        storage.append_message(chat_id, branch_id, "user", user_text)
        storage.append_message(chat_id, branch_id, "assistant", result.text)
        wm = int(params.get("sliding_window_messages", MEMORY_DEFAULTS.sliding_window_messages))
        storage.delete_old_user_assistant_keep_last(chat_id, branch_id, wm)
        if result.usage.total_tokens is not None:
            storage.add_tokens(chat_id, branch_id, result.usage.total_tokens)
        tok_display = result.usage.total_tokens
        elapsed = result.elapsed_sec
    elif strategy == MEMORY_STRATEGY_TRIPLE:
        storage.append_message(chat_id, branch_id, "user", user_text)
        tok_m, el_m = refresh_working_memory_auto(storage, agent, chat_id, branch_id, params)
        tokens_merge = tok_m
        elapsed_merge = el_m
        ctx = build_triple_context(storage, chat_id, branch_id, params)
        result = agent.complete_with_tools(
            ctx,
            tools=_working_memory_tools(),
            tool_executor=lambda n, a: _execute_working_memory_tool(storage, branch_id, n, a),
        )
        storage.append_message(chat_id, branch_id, "assistant", result.text)
        total_llm_tokens = 0
        if tokens_merge is not None:
            total_llm_tokens += tokens_merge
        if result.usage.total_tokens is not None:
            total_llm_tokens += result.usage.total_tokens
        if total_llm_tokens > 0:
            storage.add_tokens(chat_id, branch_id, total_llm_tokens)
        tok_display = total_llm_tokens if total_llm_tokens > 0 else result.usage.total_tokens
        elapsed = elapsed_merge + result.elapsed_sec
    else:
        ctx = apply_invariants_to_context(storage, branch_id, storage.get_context_messages(branch_id))
        result = agent.chat_turn_with_messages(ctx, user_text)
        storage.append_message(chat_id, branch_id, "user", user_text)
        storage.append_message(chat_id, branch_id, "assistant", result.text)
        maybe_rollup_summaries(storage, agent, branch_id)
        if result.usage.total_tokens is not None:
            storage.add_tokens(chat_id, branch_id, result.usage.total_tokens)
        tok_display = result.usage.total_tokens
        elapsed = result.elapsed_sec

    updated_branch = storage.get_branch(branch_id)
    updated_chat = storage.get_chat(chat_id)
    b_tokens = updated_branch.total_tokens if updated_branch else branch.total_tokens
    c_tokens = updated_chat.total_tokens if updated_chat else chat.total_tokens

    return SendMessageResult(
        assistant_text=result.text,
        model=result.model,
        tokens_this_turn=tok_display,
        total_tokens_branch=b_tokens,
        total_tokens_chat=c_tokens,
        elapsed_sec=elapsed,
    )


def send_message_stream(
    storage: SQLiteChatStorage,
    chat_id: int,
    branch_id: int,
    user_text: str,
    *,
    should_stop=None,
):
    """Стримит ответ токенами и в конце сохраняет результат в БД."""
    user_text = (user_text or "").strip()
    if not user_text:
        raise ValueError("Пустое сообщение")

    chat = storage.get_chat(chat_id)
    if not chat:
        raise ValueError("Чат не найден")
    branch = storage.get_branch(branch_id)
    if not branch or branch.chat_id != chat_id:
        raise ValueError("Ветка не найдена")

    strategy = normalize_memory_strategy(branch.memory_strategy)
    params = parse_strategy_params(branch)
    agent = create_agent_for_branch(storage, branch_id)
    tokens_merge: int | None = None
    elapsed_merge = 0.0

    if strategy == MEMORY_STRATEGY_TRIPLE:
        yield {"type": "status", "phase": "wm_merge", "message": "Обновляю рабочую память..."}
        storage.append_message(chat_id, branch_id, "user", user_text)
        tok_m, el_m = refresh_working_memory_auto(storage, agent, chat_id, branch_id, params)
        tokens_merge = tok_m
        elapsed_merge = el_m
        ctx = build_triple_context(storage, chat_id, branch_id, params)
        yield {"type": "status", "phase": "tools", "message": "Выполняю шаги и инструменты..."}
        final: SendMessageResult | None = None
        seen_delta = False
        for ev in agent.complete_with_tools_stream_events(
            ctx,
            tools=_working_memory_tools(),
            tool_executor=lambda n, a: _execute_working_memory_tool(storage, branch_id, n, a),
            should_stop=should_stop,
        ):
            if ev.type == "delta" and ev.delta is not None:
                if not seen_delta:
                    seen_delta = True
                    yield {"type": "status", "phase": "answer", "message": "Формирую ответ..."}
                yield {"type": "delta", "delta": ev.delta}
                continue
            if ev.type != "done" or ev.result is None:
                continue
            result = ev.result
            if result.text:
                storage.append_message(chat_id, branch_id, "assistant", result.text)
            total_llm_tokens = 0
            if tokens_merge is not None:
                total_llm_tokens += tokens_merge
            if result.usage.total_tokens is not None:
                total_llm_tokens += result.usage.total_tokens
            if total_llm_tokens > 0:
                storage.add_tokens(chat_id, branch_id, total_llm_tokens)
            tok_display = total_llm_tokens if total_llm_tokens > 0 else result.usage.total_tokens
            updated_branch = storage.get_branch(branch_id)
            updated_chat = storage.get_chat(chat_id)
            b_tokens = updated_branch.total_tokens if updated_branch else branch.total_tokens
            c_tokens = updated_chat.total_tokens if updated_chat else chat.total_tokens
            final = SendMessageResult(
                assistant_text=result.text,
                model=result.model,
                tokens_this_turn=tok_display,
                total_tokens_branch=b_tokens,
                total_tokens_chat=c_tokens,
                elapsed_sec=elapsed_merge + result.elapsed_sec,
            )
            yield {"type": "stopped", "stopped": bool(ev.stopped)}
        if not final:
            raise RuntimeError("Поток завершился без финального результата")
        yield {"type": "done", "result": final}
        return

    if strategy == MEMORY_STRATEGY_STICKY:
        yield {"type": "status", "phase": "facts", "message": "Обновляю sticky facts..."}
        storage.append_message(chat_id, branch_id, "user", user_text)
        tok_m, el_m = refresh_sticky_facts(storage, agent, chat_id, branch_id, params)
        tokens_merge = tok_m
        elapsed_merge = el_m
        ctx = build_sticky_context_after_user(storage, chat_id, branch_id, params)
        stream_messages = ctx
    elif strategy == MEMORY_STRATEGY_DEFAULT:
        storage.append_message(chat_id, branch_id, "user", user_text)
        ctx = build_context_default(storage, branch_id)
        stream_messages = [*ctx, {"role": "user", "content": user_text}]
    elif strategy == MEMORY_STRATEGY_SLIDING:
        storage.append_message(chat_id, branch_id, "user", user_text)
        ctx = build_context_sliding(storage, chat_id, branch_id, params)
        stream_messages = [*ctx, {"role": "user", "content": user_text}]
    else:
        storage.append_message(chat_id, branch_id, "user", user_text)
        ctx = apply_invariants_to_context(storage, branch_id, storage.get_context_messages(branch_id))
        stream_messages = [*ctx, {"role": "user", "content": user_text}]

    final: SendMessageResult | None = None
    emitted_answer_status = False
    for ev in agent.complete_messages_stream_events(stream_messages, should_stop=should_stop):
        if ev.type == "delta" and ev.delta is not None:
            if not emitted_answer_status:
                emitted_answer_status = True
                yield {"type": "status", "phase": "answer", "message": "Формирую ответ..."}
            yield {"type": "delta", "delta": ev.delta}
            continue
        if ev.type != "done" or ev.result is None:
            continue

        result = ev.result
        storage.append_message(chat_id, branch_id, "assistant", result.text)
        if strategy == MEMORY_STRATEGY_SUMMARY:
            maybe_rollup_summaries(storage, agent, branch_id)
        if strategy == MEMORY_STRATEGY_SLIDING:
            wm = int(params.get("sliding_window_messages", MEMORY_DEFAULTS.sliding_window_messages))
            storage.delete_old_user_assistant_keep_last(chat_id, branch_id, wm)

        total_llm_tokens = 0
        if tokens_merge is not None:
            total_llm_tokens += tokens_merge
        if result.usage.total_tokens is not None:
            total_llm_tokens += result.usage.total_tokens
        if total_llm_tokens > 0:
            storage.add_tokens(chat_id, branch_id, total_llm_tokens)
        tok_display = total_llm_tokens if total_llm_tokens > 0 else result.usage.total_tokens

        updated_branch = storage.get_branch(branch_id)
        updated_chat = storage.get_chat(chat_id)
        b_tokens = updated_branch.total_tokens if updated_branch else branch.total_tokens
        c_tokens = updated_chat.total_tokens if updated_chat else chat.total_tokens
        final = SendMessageResult(
            assistant_text=result.text,
            model=result.model,
            tokens_this_turn=tok_display,
            total_tokens_branch=b_tokens,
            total_tokens_chat=c_tokens,
            elapsed_sec=elapsed_merge + result.elapsed_sec,
        )
        yield {"type": "stopped", "stopped": bool(ev.stopped)}

    if not final:
        raise RuntimeError("Поток завершился без финального результата")
    yield {"type": "done", "result": final}


def resume_last_answer_stream(
    storage: SQLiteChatStorage,
    chat_id: int,
    branch_id: int,
    *,
    should_stop=None,
):
    """Продолжает последний ответ ассистента без добавления нового user-сообщения."""
    chat = storage.get_chat(chat_id)
    if not chat:
        raise ValueError("Чат не найден")
    branch = storage.get_branch(branch_id)
    if not branch or branch.chat_id != chat_id:
        raise ValueError("Ветка не найдена")

    strategy = normalize_memory_strategy(branch.memory_strategy)
    params = parse_strategy_params(branch)
    agent = create_agent_for_branch(storage, branch_id)

    if strategy == MEMORY_STRATEGY_STICKY:
        ctx = build_sticky_context_after_user(storage, chat_id, branch_id, params)
    elif strategy == MEMORY_STRATEGY_DEFAULT:
        ctx = build_context_default(storage, branch_id)
    elif strategy == MEMORY_STRATEGY_SLIDING:
        ctx = build_context_sliding(storage, chat_id, branch_id, params)
    elif strategy == MEMORY_STRATEGY_TRIPLE:
        ctx = build_triple_context(storage, chat_id, branch_id, params)
    else:
        ctx = apply_invariants_to_context(storage, branch_id, storage.get_context_messages(branch_id))

    last_assistant = storage.get_last_assistant_message(chat_id, branch_id)
    if not last_assistant or not last_assistant.content.strip():
        raise ValueError("Нет остановленного ответа для продолжения")

    stream_messages = [
        *ctx,
        {
            "role": "system",
            "content": (
                "Продолжи последний ответ ассистента с места остановки. "
                "Не повторяй уже написанную часть, выдай только продолжение."
            ),
        },
    ]

    final: SendMessageResult | None = None
    for ev in agent.complete_messages_stream_events(stream_messages, should_stop=should_stop):
        if ev.type == "delta" and ev.delta is not None:
            yield {"type": "status", "phase": "answer", "message": "Продолжаю ответ..."}
            yield {"type": "delta", "delta": ev.delta}
            continue
        if ev.type != "done" or ev.result is None:
            continue
        result = ev.result
        if result.text:
            merged = last_assistant.content + result.text
            storage.update_message_content(chat_id, last_assistant.message_id, merged)
        if result.usage.total_tokens is not None:
            storage.add_tokens(chat_id, branch_id, result.usage.total_tokens)
        updated_branch = storage.get_branch(branch_id)
        updated_chat = storage.get_chat(chat_id)
        b_tokens = updated_branch.total_tokens if updated_branch else branch.total_tokens
        c_tokens = updated_chat.total_tokens if updated_chat else chat.total_tokens
        final = SendMessageResult(
            assistant_text=result.text,
            model=result.model,
            tokens_this_turn=result.usage.total_tokens,
            total_tokens_branch=b_tokens,
            total_tokens_chat=c_tokens,
            elapsed_sec=result.elapsed_sec,
        )
        yield {"type": "stopped", "stopped": bool(ev.stopped)}

    if not final:
        raise RuntimeError("Поток продолжения завершился без результата")
    yield {"type": "done", "result": final}


def create_agent(
    *,
    system_prompt: str | None = None,
    timeout_sec: float | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> LLMAgent:
    config = LLMConfig.from_env()
    return LLMAgent(
        config,
        system_prompt=system_prompt or SETTINGS.default_system_prompt,
        timeout_sec=timeout_sec if timeout_sec is not None else SETTINGS.default_timeout_sec,
        temperature=temperature if temperature is not None else SETTINGS.default_temperature,
        max_tokens=max_tokens if max_tokens is not None else SETTINGS.default_max_tokens,
    )
