"""Any OpenAI-compatible endpoint: OmniRoute, OpenRouter, OpenAI, Groq, Ollama, LM Studio..."""
from __future__ import annotations

from openai import AsyncOpenAI, APIError

from .base import LLMError, LLMProvider


class OpenAICompatProvider(LLMProvider):
    def __init__(self, profile: dict):
        self.model = profile.get("model") or ""
        if not self.model:
            raise LLMError(f"В профиле «{profile.get('name')}» не указана модель.")
        headers = profile.get("headers") or {}
        if isinstance(headers, str):
            headers = dict(
                (k.strip(), v.strip()) for k, v in
                (line.split(":", 1) for line in headers.splitlines() if ":" in line)
            )
        self.client = AsyncOpenAI(
            base_url=(profile.get("base_url") or "").rstrip("/") or None,
            api_key=profile.get("api_key") or "not-needed",
            default_headers=headers or None,
            timeout=180,
        )

    async def chat(self, system: str, messages: list[dict], max_tokens: int = 2000) -> str:
        msgs = [{"role": "system", "content": system}] + messages
        try:
            resp = await self.client.chat.completions.create(
                model=self.model, messages=msgs, max_tokens=max_tokens,
            )
        except APIError as e:
            raise LLMError(f"Ошибка LLM ({self.model}): {e}") from e
        except Exception as e:  # connection errors etc.
            raise LLMError(f"Не удалось подключиться к LLM: {e}") from e
        if not resp.choices:
            raise LLMError("LLM вернула пустой ответ")
        return resp.choices[0].message.content or ""
