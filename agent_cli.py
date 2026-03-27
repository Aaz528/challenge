#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
from datetime import datetime
from pathlib import Path
import sys

from app_settings import SETTINGS, SUMMARY_SETTINGS
from llm_agent import LLMAgent, LLMConfig
from sqlite_chat_storage import SQLiteChatStorage


def _print_result(result, overall_tokens: int | None) -> None:
    print("\n" + "=" * 60)
    print(f"Ответ (модель: {result.model})")
    print("=" * 60)
    print(result.text)
    print("\n" + "-" * 60)
    tok = "н/д" if result.usage.total_tokens is None else str(result.usage.total_tokens)
    overall = "н/д" if overall_tokens is None else str(overall_tokens)
    print(f"Токены: {tok} | Итого токенов: {overall} | Время ответа: {result.elapsed_sec:.2f} с")
    print("-" * 60)


def _parse_toon(text: str) -> tuple[list[dict[str, str]], int | None]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "TOON/1":
        raise ValueError("Неизвестный формат TOON")

    messages: list[dict[str, str]] = []
    overall_tokens: int | None = None
    for line in lines[1:]:
        if not line.strip():
            continue
        role, payload = line.split("\t", 1)
        content = base64.b64decode(payload.encode("ascii")).decode("utf-8")
        if role == "meta":
            # Ожидаем: tokens_total=<int>
            if content.startswith("tokens_total="):
                try:
                    overall_tokens = int(content.split("=", 1)[1].strip())
                except (TypeError, ValueError):
                    overall_tokens = None
            continue
        messages.append({"role": role, "content": content})
    return messages, overall_tokens


def _auto_title(file_name: str, messages: list[dict[str, str]]) -> str:
    lower = file_name.lower()
    fixed = SETTINGS.fixed_import_titles.get(lower)
    if fixed:
        return fixed

    first_user = ""
    for m in messages:
        if m.get("role") == "user":
            first_user = str(m.get("content", "")).strip()
            break
    if not first_user:
        return f"Импорт из {file_name}"

    words = first_user.replace("\n", " ").split()
    short = " ".join(words[:6]).strip()
    return short[:80] if short else f"Импорт из {file_name}"


def _migrate_toon_chats(storage: SQLiteChatStorage, default_system_prompt: str) -> None:
    for toon_file in sorted(Path.cwd().glob("*.toon")):
        try:
            raw = toon_file.read_text(encoding="utf-8")
            messages, overall_tokens = _parse_toon(raw)
            if not messages:
                continue
            system_prompt = default_system_prompt
            if messages and messages[0].get("role") == "system":
                system_prompt = str(messages[0].get("content", default_system_prompt))
            title = _auto_title(toon_file.name, messages)
            storage.get_or_create_chat_from_source(
                source_key=f"toon:{toon_file.name}",
                title=title,
                system_prompt=system_prompt,
                messages=messages,
                total_tokens=overall_tokens or 0,
            )
        except Exception:
            # Не валим запуск, если какой-то старый файл поврежден.
            continue


def _build_unsummarized_turns(storage: SQLiteChatStorage, chat_id: int) -> list[tuple[int, int, list[dict[str, str]]]]:
    rows = [r for r in storage.get_unsummarized_message_rows(chat_id) if r.is_summarized == 0]
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


def _maybe_rollup_summaries(storage: SQLiteChatStorage, agent: LLMAgent, chat_id: int) -> None:
    """
    Сводим историю блоками по 4 завершенных user+assistant хода,
    но всегда оставляем 2 последних хода в несвернутом виде.
    """
    while True:
        turns = _build_unsummarized_turns(storage, chat_id)
        if len(turns) < SUMMARY_SETTINGS.min_turns_to_rollup:
            return
        candidate = turns[: -SUMMARY_SETTINGS.keep_last_turns]
        if len(candidate) < SUMMARY_SETTINGS.rollup_turns_per_batch:
            return

        # Берем блок для сворачивания из архивной зоны.
        block = candidate[-SUMMARY_SETTINGS.rollup_turns_per_batch :]
        flat_messages: list[dict[str, str]] = []
        for _, _, turn_messages in block:
            flat_messages.extend(turn_messages)

        summary_text = agent.summarize_messages(flat_messages)
        from_id = block[0][0]
        to_id = block[-1][1]
        storage.create_summary_and_mark(
            chat_id=chat_id,
            summary_text=summary_text,
            from_message_id=from_id,
            to_message_id=to_id,
        )


def _select_or_create_chat(storage: SQLiteChatStorage, system_prompt: str) -> int:
    while True:
        chats = storage.list_chats(limit=SETTINGS.chat_list_limit)
        print("\nДоступные чаты:")
        if chats:
            for i, c in enumerate(chats, start=1):
                print(f"  {i}) [{c.chat_id}] {c.title} (итого токенов: {c.total_tokens})")
        else:
            print("  (пока нет чатов)")

        print("  n) Новый чат")
        print("  q) Выход")
        choice = input("Выберите чат: ").strip().lower()
        if choice in SETTINGS.exit_commands:
            raise KeyboardInterrupt
        if choice == "n":
            title = input("Заголовок нового чата (Enter = авто): ").strip()
            if not title:
                title = "Новый чат " + datetime.now().strftime("%Y-%m-%d %H:%M")
            return storage.create_chat(title=title, system_prompt=system_prompt)
        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(chats):
                return chats[idx - 1].chat_id
        print("Некорректный выбор, попробуйте снова.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LLM Agent CLI")
    parser.add_argument("--prompt", "-p", type=str, default="", help="Текст запроса пользователя")
    parser.add_argument("--temperature", type=float, default=SETTINGS.default_temperature, help="Sampling temperature")
    parser.add_argument("--max-tokens", type=int, default=SETTINGS.default_max_tokens, help="Max output tokens")
    parser.add_argument(
        "--system-prompt",
        type=str,
        default=SETTINGS.default_system_prompt,
        help="System prompt для модели",
    )
    parser.add_argument("--timeout", type=float, default=SETTINGS.default_timeout_sec, help="Timeout запроса к LLM (сек)")
    parser.add_argument("--chat-id", type=int, default=0, help="ID существующего чата в БД")
    parser.add_argument("--new-chat-title", type=str, default="", help="Создать новый чат с указанным заголовком")
    parser.add_argument("--db-path", type=str, default=SETTINGS.default_db_path, help="Путь к SQLite-файлу базы чатов")
    args = parser.parse_args(argv)

    storage: SQLiteChatStorage | None = None
    try:
        config = LLMConfig.from_env()
        agent = LLMAgent(
            config,
            system_prompt=args.system_prompt,
            timeout_sec=args.timeout,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
        )
        storage = SQLiteChatStorage(db_path=args.db_path)
        storage.ensure_schema()
        _migrate_toon_chats(storage, args.system_prompt)
    except Exception as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 1

    try:
        if args.chat_id > 0:
            chat_info = storage.get_chat(args.chat_id)
            if not chat_info:
                print(f"Чат с ID={args.chat_id} не найден.", file=sys.stderr)
                return 1
            chat_id = chat_info.chat_id
        elif args.new_chat_title.strip():
            chat_id = storage.create_chat(title=args.new_chat_title.strip(), system_prompt=args.system_prompt)
            chat_info = storage.get_chat(chat_id)
        else:
            try:
                chat_id = _select_or_create_chat(storage, args.system_prompt)
            except KeyboardInterrupt:
                print("\nВыход.")
                return 0
            chat_info = storage.get_chat(chat_id)

        if not chat_info:
            print("Не удалось загрузить выбранный чат.", file=sys.stderr)
            return 1

        overall_tokens = chat_info.total_tokens

        prompt = (args.prompt or "").strip()
        if prompt:
            try:
                context_messages = storage.get_context_messages(chat_id)
                result = agent.chat_turn_with_messages(context_messages, prompt)
                storage.append_message(chat_id, "user", prompt)
                storage.append_message(chat_id, "assistant", result.text)
                _maybe_rollup_summaries(storage, agent, chat_id)
            except Exception as e:
                print(f"Ошибка: {e}", file=sys.stderr)
                return 1
            if result.usage.total_tokens is not None:
                overall_tokens = (overall_tokens or 0) + result.usage.total_tokens
                storage.add_tokens(chat_id, result.usage.total_tokens)
            _print_result(result, overall_tokens)
            return 0

        print(f"\nТекущий чат: [{chat_id}] {chat_info.title}")
        print("Режим диалога: введите запрос. Для выхода: exit | quit | q | /exit")
        while True:
            user_in = input("Вы: ").strip()
            if not user_in:
                continue
            if user_in.lower() in SETTINGS.exit_commands:
                break
            try:
                context_messages = storage.get_context_messages(chat_id)
                result = agent.chat_turn_with_messages(context_messages, user_in)
                storage.append_message(chat_id, "user", user_in)
                storage.append_message(chat_id, "assistant", result.text)
                _maybe_rollup_summaries(storage, agent, chat_id)
            except Exception as e:
                print(f"Ошибка: {e}", file=sys.stderr)
                continue
            if result.usage.total_tokens is not None:
                overall_tokens = (overall_tokens or 0) + result.usage.total_tokens
                storage.add_tokens(chat_id, result.usage.total_tokens)
            _print_result(result, overall_tokens)
    finally:
        if storage is not None:
            storage.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

