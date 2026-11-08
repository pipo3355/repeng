"""Anthropic Messages API via the official SDK."""
from __future__ import annotations

import anthropic

from .base import LLMError, LLMProvider

# Models that accept the server-side refusal fallback ("default" mode).
_FALLBACK_MODELS = ("claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5")


class AnthropicProvider(LLMProvider):
    def __init__(self, profile: dict):
        self.model = profile.get("model") or "claude-opus-5-5"
        # Chat-tutor turns are latency-sensitive: low effort by default.
        # "none" omits the parameter (for older models without effort support).
        self.effort = profile.get("effort") or "low"
        self.fallbacks = profile.get("fallbacks", True) and self.model.startswith(_FALLBACK_MODELS)
        kwargs = {"api_key": profile.get("api_key") or None, "timeout": 180.0}
        if profile.get("base_url"):
            kwargs["base_url"] = profile["base_url"]
        self.client = anthropic.AsyncAnthropic(**kwargs)

    async def chat(self, system: str, messages: list[dict], max_tokens: int = 2000) -> str:
        params = dict(
            model=self.model,
            max_tokens=max(max_tokens, 4000),  # leave room for adaptive thinking
            system=system,
            messages=messages,
        )
        if self.effort != "none":
            params["output_config"] = {"effort": self.effort}
        try:
            if self.fallbacks:
                resp = await self.client.beta.messages.create(
                    **params, betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                )
            else:
                resp = await self.client.messages.create(**params)
        except anthropic.AuthenticationError as e:
            raise LLMError("Anthropic: неверный API-ключ") from e
        except anthropic.NotFoundError as e:
            raise LLMError(f"Anthropic: модель {self.model} не найдена") from e
        except anthropic.RateLimitError as e:
            raise LLMError("Anthropic: превышен лимит запросов, попробуйте позже") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"Anthropic API {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise LLMError(f"Anthropic: нет соединения ({e})") from e
        if resp.stop_reason == "refusal":
            raise LLMError("Модель отказалась отвечать на этот запрос")
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
