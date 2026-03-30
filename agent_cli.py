#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
import sys

from app_settings import SETTINGS
from chat_service import send_message
from sqlite_chat_storage import SQLiteChatStorage


def _print_result(result, overall_tokens: int | None) -> None:
    print("\n" + "=" * 60)
    print(f"Ответ (модель: {result.model})")
    print("=" * 60)
    print(result.assistant_text)
    print("\n" + "-" * 60)
    tok = "н/д" if result.tokens_this_turn is None else str(result.tokens_this_turn)
    overall = "н/д" if overall_tokens is None else str(overall_tokens)
    branch_tok = "н/д" if result.total_tokens_branch is None else str(result.total_tokens_branch)
    print(
        f"Токены: {tok} | Итого (ветка): {branch_tok} | Итого (чат): {overall} | Время: {result.elapsed_sec:.2f} с"
    )
    print("-" * 60)


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


def _select_branch(storage: SQLiteChatStorage, chat_id: int) -> int:
    branches = storage.list_branches(chat_id)
    if not branches:
        raise RuntimeError("У чата нет веток")
    if len(branches) == 1:
        return branches[0].branch_id
    print("\nВетки:")
    for i, b in enumerate(branches, start=1):
        extra = f" ← от #{b.fork_after_message_id}" if b.parent_branch_id else ""
        print(f"  {i}) [{b.branch_id}] {b.title}{extra} (токенов: {b.total_tokens})")
    while True:
        choice = input("Выберите ветку (номер): ").strip()
        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(branches):
                return branches[idx - 1].branch_id
        print("Некорректный выбор.")


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
    parser.add_argument("--branch-id", type=int, default=0, help="ID ветки (0 = основная ветка чата)")
    parser.add_argument("--new-chat-title", type=str, default="", help="Создать новый чат с указанным заголовком")
    parser.add_argument("--db-path", type=str, default=SETTINGS.default_db_path, help="Путь к SQLite-файлу базы чатов")
    args = parser.parse_args(argv)

    storage: SQLiteChatStorage | None = None
    try:
        storage = SQLiteChatStorage(db_path=args.db_path)
        storage.ensure_schema()
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

        if args.branch_id > 0:
            br = storage.get_branch(args.branch_id)
            if not br or br.chat_id != chat_id:
                print("Ветка не найдена или не относится к этому чату.", file=sys.stderr)
                return 1
            branch_id = br.branch_id
        else:
            try:
                main_id = storage.get_main_branch_id(chat_id)
                if main_id is None:
                    branch_id = _select_branch(storage, chat_id)
                elif len(storage.list_branches(chat_id)) > 1 and not args.prompt:
                    branch_id = _select_branch(storage, chat_id)
                else:
                    branch_id = main_id
            except RuntimeError as e:
                print(str(e), file=sys.stderr)
                return 1

        overall_tokens = chat_info.total_tokens

        prompt = (args.prompt or "").strip()
        if prompt:
            try:
                result = send_message(storage, chat_id, branch_id, prompt)
            except Exception as e:
                print(f"Ошибка: {e}", file=sys.stderr)
                return 1
            overall_tokens = result.total_tokens_chat
            _print_result(result, overall_tokens)
            return 0

        br_info = storage.get_branch(branch_id)
        print(f"\nТекущий чат: [{chat_id}] {chat_info.title} | ветка: [{branch_id}] {br_info.title if br_info else '?'}")
        print("Режим диалога: введите запрос. Для выхода: exit | quit | q | /exit")
        while True:
            user_in = input("Вы: ").strip()
            if not user_in:
                continue
            if user_in.lower() in SETTINGS.exit_commands:
                break
            try:
                result = send_message(storage, chat_id, branch_id, user_in)
            except Exception as e:
                print(f"Ошибка: {e}", file=sys.stderr)
                continue
            overall_tokens = result.total_tokens_chat
            _print_result(result, overall_tokens)
    finally:
        if storage is not None:
            storage.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
