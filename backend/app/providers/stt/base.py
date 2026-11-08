"""Speech-to-text providers.

provider values:
  browser        - recognition happens in the browser (Web Speech API), text arrives with the audio
  openai_compat  - /audio/transcriptions on OpenAI, Groq, a local whisper server, OmniRoute...
  local_whisper  - faster-whisper on this machine
  audio_llm      - audio-capable chat model (Gemini...) from an LLM profile
  azure          - Azure Speech (the pronunciation call returns the recognized text)
"""
from __future__ import annotations

import asyncio


class STTError(RuntimeError):
    pass


async def transcribe(cfg: dict, wav: bytes, settings: dict) -> str:
    p = cfg.get("provider", "browser")
    if p == "openai_compat":
        from openai import AsyncOpenAI

        client = AsyncOpenAI(base_url=cfg.get("base_url") or None, api_key=cfg.get("api_key") or "not-needed", timeout=120)
        try:
            r = await client.audio.transcriptions.create(
                model=cfg.get("model") or "whisper-1",
                file=("speech.wav", wav, "audio/wav"),
                language="en",
                prompt="Transcribe exactly what the speaker says, including grammar mistakes. Do not correct grammar.",
            )
        except Exception as e:
            raise STTError(f"Ошибка распознавания речи: {e}") from e
        return (r.text or "").strip()
    if p == "local_whisper":
        from . import local_whisper

        return await asyncio.to_thread(local_whisper.transcribe, wav, cfg.get("local_model") or "small.en")
    if p == "audio_llm":
        from .. import audio_llm

        res = await audio_llm.analyze(wav, audio_llm.find_profile(settings, cfg.get("llm_profile")), settings)
        return res["transcript"]
    if p == "azure":
        from ..pron import azure

        res = await asyncio.to_thread(azure.assess, wav, None, settings)
        return res.get("recognized", "")
    raise STTError("Распознавание речи на сервере не настроено (выбран браузерный режим)")
