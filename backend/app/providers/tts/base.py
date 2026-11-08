"""Server-side text-to-speech. provider: browser (handled in JS) | openai_compat | azure."""
from __future__ import annotations

import re
from xml.sax.saxutils import escape

import httpx

_RU_RUN = re.compile(r"[А-Яа-яЁё][А-Яа-яЁё0-9\s.,!?;:«»\"'()\-–—…]*")


def split_by_language(text: str) -> list[tuple[bool, str]]:
    """[(is_russian, fragment)] - lets each fragment be read by a voice of its own language."""
    parts, last = [], 0
    for m in _RU_RUN.finditer(text):
        if m.start() > last:
            parts.append((False, text[last:m.start()]))
        parts.append((True, m.group(0)))
        last = m.end()
    if last < len(text):
        parts.append((False, text[last:]))
    return [(ru, t.strip()) for ru, t in parts if re.search(r"\w", t)]


class TTSError(RuntimeError):
    pass


async def synthesize(text: str, settings: dict, rate: float | None = None) -> tuple[bytes, str]:
    cfg = settings["tts"]
    p = cfg.get("provider", "browser")
    rate = rate or float(cfg.get("rate") or 1.0)
    if p == "openai_compat":
        from openai import AsyncOpenAI

        client = AsyncOpenAI(base_url=cfg.get("base_url") or None, api_key=cfg.get("api_key") or "not-needed", timeout=60)
        try:
            r = await client.audio.speech.create(
                model=cfg.get("model") or "tts-1", voice=cfg.get("voice") or "alloy",
                input=text, speed=rate, response_format="mp3",
            )
        except Exception as e:
            raise TTSError(f"Ошибка синтеза речи: {e}") from e
        return r.content, "audio/mpeg"
    if p == "azure":
        az = settings["azure"]
        if not az.get("key") or not az.get("region"):
            raise TTSError("Не заданы ключ и регион Azure")
        voice = cfg.get("azure_voice") or "en-US-AvaMultilingualNeural"
        ru_voice = cfg.get("azure_ru_voice") or "ru-RU-SvetlanaNeural"
        pct = int(round((rate - 1.0) * 100))
        body = "".join(
            f'<voice name="{escape(ru_voice if ru else voice)}"><prosody rate="{max(pct, 0) if ru else pct:+d}%">{escape(t)}</prosody></voice>'
            for ru, t in split_by_language(text)
        )
        ssml = f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">{body}</speak>'
        url = f"https://{az['region']}.tts.speech.microsoft.com/cognitiveservices/v1"
        headers = {
            "Ocp-Apim-Subscription-Key": az["key"],
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
            "User-Agent": "repeng",
        }
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(url, content=ssml.encode("utf-8"), headers=headers)
        if r.status_code != 200:
            raise TTSError(f"Azure TTS {r.status_code}: {r.text[:200]}")
        return r.content, "audio/mpeg"
    raise TTSError("Выбран браузерный синтез речи")
