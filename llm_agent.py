from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any

import requests
from dotenv import load_dotenv


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    base_url: str
    model: str

    @classmethod
    def from_env(cls) -> "LLMConfig":
        load_dotenv()

        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        base_url = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1").strip()
        model = os.environ.get("LLM_MODEL", "gpt-3.5-turbo").strip()

        base_url = base_url.rstrip("/")
        return cls(api_key=api_key, base_url=base_url, model=model)


@dataclass(frozen=True)
class LLMUsage:
    total_tokens: int | None
    prompt_tokens: int | None
    completion_tokens: int | None


@dataclass(frozen=True)
class AgentResult:
    text: str
    model: str
    usage: LLMUsage
    elapsed_sec: float
    raw: dict[str, Any] | None = None


@dataclass
class ConversationState:
    messages: list[dict[str, str]]

    @classmethod
    def new(cls, system_prompt: str) -> "ConversationState":
        return cls(messages=[{"role": "system", "content": system_prompt}])


class LLMAgent:
    """
    Одноуровневый агент: принимает user query, формирует сообщения,
    отправляет их в OpenAI-совместимый Chat Completions endpoint и возвращает результат.
    """

    def __init__(
        self,
        config: LLMConfig | None = None,
        *,
        system_prompt: str = "Отвечай по существу запроса пользователя.",
        timeout_sec: float = 60.0,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> None:
        self._config = config or LLMConfig.from_env()
        self._system_prompt = system_prompt
        self._timeout_sec = timeout_sec
        self._temperature = temperature
        self._max_tokens = max_tokens

    def new_conversation(self) -> ConversationState:
        return ConversationState.new(self._system_prompt)

    def chat_turn_with_messages(
        self,
        base_messages: list[dict[str, str]],
        user_query: str,
    ) -> AgentResult:
        """
        Один ход диалога на произвольном наборе сообщений (без мутации базы сообщений).
        """
        user_query = (user_query or "").strip()
        if not user_query:
            raise ValueError("Пустой запрос.")

        messages = [*base_messages, {"role": "user", "content": user_query}]
        return self._complete(messages, temperature=self._temperature, max_tokens=self._max_tokens)

    def summarize_messages(self, messages: list[dict[str, str]]) -> str:
        """
        Делает краткую сводку переданных сообщений для дальнейшего использования в контексте.
        """
        if not messages:
            return ""

        text_parts: list[str] = []
        for item in messages:
            role = str(item.get("role", "")).strip()
            content = str(item.get("content", "")).strip()
            if role in {"user", "assistant"} and content:
                text_parts.append(f"{role.upper()}: {content}")

        summarize_prompt = (
            "Сделай краткую структурированную сводку диалога ниже.\n"
            "Требования:\n"
            "1) 5-10 буллетов.\n"
            "2) Сохрани факты, принятые решения, ограничения и открытые вопросы.\n"
            "3) Никакой выдумки, только то, что есть в диалоге.\n\n"
            "Диалог:\n"
            + "\n".join(text_parts)
        )

        res = self._complete(
            messages=[
                {"role": "system", "content": "Ты помощник, который делает точные сводки диалогов."},
                {"role": "user", "content": summarize_prompt},
            ],
            temperature=0.1,
            max_tokens=700,
        )
        return res.text

    def complete_messages(self, messages: list[dict[str, str]]) -> AgentResult:
        """Полный список сообщений без добавления user снаружи (один запрос к LLM)."""
        if not messages:
            raise ValueError("Пустой список сообщений.")
        return self._complete(messages, temperature=self._temperature, max_tokens=self._max_tokens)

    def merge_sticky_facts(self, existing: dict[str, str], dialogue_snippet: str) -> tuple[dict[str, str], AgentResult]:
        """Обновляет key-value факты по фрагменту диалога. Отдельный вызов LLM с низкой температурой."""
        prompt = (
            "Ты ведёшь память диалога в виде JSON-объекта (строковые ключи и значения).\n"
            "Есть текущие факты и фрагмент диалога. Обнови факты: добавь новые, исправь противоречия, "
            "удали явно устаревшее. Верни ТОЛЬКО валидный JSON-объект, без markdown и пояснений.\n\n"
            f"Текущие факты:\n{json.dumps(existing, ensure_ascii=False)}\n\n"
            f"Фрагмент диалога:\n{dialogue_snippet}\n"
        )
        res = self._complete(
            messages=[
                {"role": "system", "content": "Ты помощник для структурированной памяти диалога."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=1500,
        )
        return _parse_json_object(res.text), res

    def chat_turn(self, conversation: ConversationState, user_query: str) -> AgentResult:
        """
        Один “ход” диалога: добавляет user в историю, запрашивает LLM с полной историей,
        добавляет assistant в историю и возвращает результат.
        """
        # На случай поврежденного/чужого состояния: гарантируем system в начале.
        if not conversation.messages:
            conversation.messages = ConversationState.new(self._system_prompt).messages
        elif conversation.messages[0].get("role") != "system":
            conversation.messages = ConversationState.new(self._system_prompt).messages + conversation.messages

        user_query = (user_query or "").strip()
        if not user_query:
            raise ValueError("Пустой запрос.")

        result = self._complete(
            messages=[*conversation.messages, {"role": "user", "content": user_query}],
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )
        conversation.messages.append({"role": "user", "content": user_query})
        conversation.messages.append({"role": "assistant", "content": result.text})
        return result

    def run(self, user_query: str) -> AgentResult:
        """
        Основная точка входа агента.
        """
        conversation = self.new_conversation()
        return self.chat_turn(conversation, user_query)

    @staticmethod
    def _parse_usage(usage: Any) -> LLMUsage:
        if not isinstance(usage, dict):
            return LLMUsage(total_tokens=None, prompt_tokens=None, completion_tokens=None)

        total_tokens = usage.get("total_tokens")
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")

        # Некоторые провайдеры могут отдавать только частичные поля.
        if total_tokens is None:
            try:
                p = int(prompt_tokens) if prompt_tokens is not None else 0
                c = int(completion_tokens) if completion_tokens is not None else 0
                total_tokens = p + c if (p or c) else None
            except (TypeError, ValueError):
                total_tokens = None

        return LLMUsage(
            total_tokens=int(total_tokens) if total_tokens is not None else None,
            prompt_tokens=int(prompt_tokens) if prompt_tokens is not None else None,
            completion_tokens=int(completion_tokens) if completion_tokens is not None else None,
        )

    def _complete(self, messages: list[dict[str, str]], *, temperature: float, max_tokens: int) -> AgentResult:
        if not self._config.api_key:
            raise RuntimeError("OPENAI_API_KEY не задан в .env")

        payload: dict[str, Any] = {
            "model": self._config.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }
        t0 = time.perf_counter()
        resp = requests.post(
            f"{self._config.base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=self._timeout_sec,
        )
        elapsed = time.perf_counter() - t0
        resp.raise_for_status()
        data = resp.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError("LLM вернул неожиданный формат ответа") from e

        text = str(content).strip()
        usage = self._parse_usage(data.get("usage"))
        return AgentResult(
            text=text,
            model=self._config.model,
            usage=usage,
            elapsed_sec=elapsed,
            raw=data if os.environ.get("DEBUG_LLM_AGENT") else None,
        )


def _parse_json_object(text: str) -> dict[str, str]:
    t = (text or "").strip()
    if not t:
        return {}
    if t.startswith("```"):
        inner = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
        inner = re.sub(r"\s*```\s*$", "", inner)
        t = inner.strip()
    try:
        data = json.loads(t)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in data.items():
        out[str(k)] = str(v) if v is not None else ""
    return out

