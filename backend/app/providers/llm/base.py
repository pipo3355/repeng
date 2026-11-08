from __future__ import annotations

import json
import re
from typing import Any


class LLMError(RuntimeError):
    pass


class JSONReplyError(LLMError):
    def __init__(self, msg: str, raw: str):
        super().__init__(msg)
        self.raw = raw


class LLMProvider:
    async def chat(self, system: str, messages: list[dict], max_tokens: int = 2000) -> str:
        raise NotImplementedError


def make_llm(profile: dict | None) -> LLMProvider:
    if not profile:
        raise LLMError("Не настроена языковая модель. Откройте «Настройки» и добавьте профиль LLM.")
    if profile.get("kind") == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider(profile)
    from .openai_compat import OpenAICompatProvider
    return OpenAICompatProvider(profile)


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def extract_json(text: str) -> Any:
    """Parse JSON from a model reply that may contain fences or chatter around it."""
    if text is None:
        raise ValueError("empty")
    t = text.strip()
    candidates = [t]
    candidates += [m.group(1).strip() for m in _FENCE.finditer(t)]
    start = t.find("{")
    if start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(t)):
            ch = t[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(t[start:i + 1])
                    break
    for c in candidates:
        for variant in (c, re.sub(r",\s*([}\]])", r"\1", c)):
            try:
                v = json.loads(variant)
                if isinstance(v, (dict, list)):
                    return v
            except json.JSONDecodeError:
                continue
    raise ValueError("no JSON object found")


async def chat_json(llm: LLMProvider, system: str, messages: list[dict], max_tokens: int = 2000) -> dict:
    """Ask for JSON; retry once with a reminder if parsing fails."""
    text = await llm.chat(system, messages, max_tokens)
    try:
        return extract_json(text)
    except ValueError:
        retry = messages + [
            {"role": "assistant", "content": text or "(empty)"},
            {"role": "user", "content": "Your previous answer was not valid JSON. Reply again with ONLY the JSON object in the required format."},
        ]
        text2 = await llm.chat(system, retry, max_tokens)
        try:
            return extract_json(text2)
        except ValueError as e:
            raise JSONReplyError(f"Модель вернула не-JSON ответ: {text2[:300]}", text2) from e
