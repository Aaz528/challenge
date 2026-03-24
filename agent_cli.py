#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import sys

from llm_agent import ConversationState, LLMAgent, LLMConfig


def _print_result(result) -> None:
    print("\n" + "=" * 60)
    print(f"Ответ (модель: {result.model})")
    print("=" * 60)
    print(result.text)
    print("\n" + "-" * 60)
    tok = "н/д" if result.usage.total_tokens is None else str(result.usage.total_tokens)
    print(f"Токены: {tok} | Время ответа: {result.elapsed_sec:.2f} с")
    print("-" * 60)


def _serialize_toon(messages: list[dict[str, str]]) -> str:
    # TOON v1: одна строка на сообщение, контент в base64 (utf-8), чтобы не терять переносы.
    lines = ["TOON/1"]
    for message in messages:
        role = str(message.get("role", "")).strip()
        content = str(message.get("content", ""))
        payload = base64.b64encode(content.encode("utf-8")).decode("ascii")
        lines.append(f"{role}\t{payload}")
    return "\n".join(lines) + "\n"


def _parse_toon(text: str) -> list[dict[str, str]]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "TOON/1":
        raise ValueError("Неизвестный формат TOON")

    messages: list[dict[str, str]] = []
    for line in lines[1:]:
        if not line.strip():
            continue
        role, payload = line.split("\t", 1)
        content = base64.b64decode(payload.encode("ascii")).decode("utf-8")
        messages.append({"role": role, "content": content})
    return messages


def _load_session(session_file: Path, system_prompt: str) -> ConversationState:
    if not session_file.exists():
        return ConversationState.new(system_prompt)
    try:
        raw = session_file.read_text(encoding="utf-8")
        if session_file.suffix.lower() == ".toon":
            messages = _parse_toon(raw)
        else:
            data = json.loads(raw)
            messages = data.get("messages")
        if isinstance(messages, list) and messages and isinstance(messages[0], dict) and messages[0].get("role") == "system":
            return ConversationState(messages=messages)  # type: ignore[arg-type]
        return ConversationState.new(system_prompt)
    except Exception:
        return ConversationState.new(system_prompt)


def _save_session(session_file: Path, conversation: ConversationState) -> None:
    session_file.parent.mkdir(parents=True, exist_ok=True)
    if session_file.suffix.lower() == ".toon":
        session_file.write_text(_serialize_toon(conversation.messages), encoding="utf-8")
    else:
        session_file.write_text(
            json.dumps({"messages": conversation.messages}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LLM Agent CLI")
    parser.add_argument("--prompt", "-p", type=str, default="", help="Текст запроса пользователя")
    parser.add_argument("--temperature", type=float, default=0.3, help="Sampling temperature")
    parser.add_argument("--max-tokens", type=int, default=1024, help="Max output tokens")
    parser.add_argument(
        "--system-prompt",
        type=str,
        default="Отвечай по существу запроса пользователя.",
        help="System prompt для модели",
    )
    parser.add_argument("--timeout", type=float, default=60.0, help="Timeout запроса к LLM (сек)")
    parser.add_argument(
        "--session-file",
        type=str,
        default="chat.toon",
        help="Файл сессии (.toon рекомендован). Контекст сохраняется между запусками.",
    )
    parser.add_argument(
        "--reset-session",
        action="store_true",
        help="Если session-file задан — удалить файл перед началом.",
    )
    args = parser.parse_args(argv)

    try:
        config = LLMConfig.from_env()
        agent = LLMAgent(
            config,
            system_prompt=args.system_prompt,
            timeout_sec=args.timeout,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
        )
    except Exception as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 1

    session_path = Path(args.session_file).expanduser() if args.session_file else None
    if session_path and args.reset_session and session_path.exists():
        try:
            session_path.unlink()
        except OSError:
            pass

    if session_path:
        conversation = _load_session(session_path, args.system_prompt)
    else:
        conversation = agent.new_conversation()

    def save_if_needed() -> None:
        if session_path:
            _save_session(session_path, conversation)

    prompt = (args.prompt or "").strip()
    if prompt:
        try:
            result = agent.chat_turn(conversation, prompt)
        except Exception as e:
            print(f"Ошибка: {e}", file=sys.stderr)
            return 1
        _print_result(result)
        save_if_needed()
        return 0

    # Если prompt не задан — ведем диалог (контекст сохраняется в рамках процесса).
    print("Режим диалога: введите запрос. Для выхода: exit | quit | q | /exit")
    while True:
        user_in = input("Вы: ").strip()
        if not user_in:
            continue
        if user_in.lower() in {"exit", "quit", "q", "/exit"}:
            break
        try:
            result = agent.chat_turn(conversation, user_in)
        except Exception as e:
            print(f"Ошибка: {e}", file=sys.stderr)
            continue
        _print_result(result)
        save_if_needed()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

