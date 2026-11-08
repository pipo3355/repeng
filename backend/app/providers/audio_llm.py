"""Audio-capable chat models (Gemini, MiMo, gpt-4o-audio...) via an OpenAI-compatible gateway.

One call returns a verbatim transcript and/or "by ear" pronunciation feedback.
The feedback is qualitative: scores from a chat model are not calibrated, so these results
are flagged approximate and do not feed the per-phoneme statistics.
"""
from __future__ import annotations

import base64
import re

from openai import AsyncOpenAI

from .llm.base import LLMError, extract_json

PROMPT = """You are an expert English pronunciation coach and a precise transcriber.
The audio is a {native}-speaking learner of English (target accent: {accent}).
{reference_line}
Return ONLY a JSON object:
{
  "transcript": "verbatim transcript of what was actually said, keeping grammar mistakes and wrong words; do NOT correct anything; empty string if no speech",
  "pronunciation": {
    "overall": 0-100,
    "issues": [{"word": "think", "expected": "θ", "heard": "s", "tip": "short practical articulation tip in {explain_lang}"}],
    "intonation": "one short comment in {explain_lang} about rhythm/intonation, or empty string"
  }
}
Rules: list only clearly audible, typical accent problems (max 5, worst first); use IPA for "expected"/"heard";
if pronunciation is good, return an empty "issues" list. Never invent problems you did not hear."""


def find_profile(settings: dict, profile_id: str | None) -> dict:
    for p in settings["llm_profiles"]:
        if p["id"] == profile_id:
            return p
    raise LLMError("Не выбран профиль аудио-модели (Настройки → голос)")


async def analyze(wav: bytes, profile: dict, settings: dict, reference: str | None = None) -> dict:
    if profile.get("kind") == "anthropic":
        raise LLMError("Модели Anthropic не принимают аудио. Выберите OpenAI-совместимый профиль с аудио-моделью (например Gemini).")
    from ..db import db
    from ..tutor import prompts
    from ..tutor.memory import get_profile

    with db() as conn:
        native = get_profile(conn)["native_lang"] or "Russian"
    lang = prompts.LANG_NAMES.get(settings["tutor"].get("explain_lang", "ru"), "Russian")
    ref_line = (f'The learner was asked to read this text aloud: "{reference}". Transcribe what they actually said.'
                if reference else "This is free speech in a conversation.")
    text = prompts.fill(PROMPT, native=native, accent=settings["tutor"].get("accent", "en-US"),
                        reference_line=ref_line, explain_lang=lang)

    client = AsyncOpenAI(base_url=(profile.get("base_url") or "").rstrip("/") or None,
                         api_key=profile.get("api_key") or "not-needed", timeout=120)
    content = [
        {"type": "text", "text": text},
        {"type": "input_audio", "input_audio": {"data": base64.b64encode(wav).decode(), "format": "wav"}},
    ]
    try:
        resp = await client.chat.completions.create(
            model=profile.get("model"), messages=[{"role": "user", "content": content}], max_tokens=1500)
    except Exception as e:
        raise LLMError(f"Аудио-модель {profile.get('model')}: {e}") from e
    raw = (resp.choices[0].message.content or "") if resp.choices else ""
    try:
        data = extract_json(raw)
    except ValueError as e:
        raise LLMError(f"Аудио-модель вернула не-JSON: {raw[:200]}") from e
    transcript = str(data.get("transcript") or "").strip()
    return {"transcript": transcript, "pron": to_schema(data.get("pronunciation") or {}, reference or transcript)}


def to_schema(p: dict, text: str) -> dict:
    """Map qualitative feedback onto the shared pronunciation schema."""
    issues = [i for i in (p.get("issues") or []) if isinstance(i, dict) and i.get("word")]
    by_word: dict[str, list[dict]] = {}
    for i in issues:
        by_word.setdefault(_norm(i["word"]), []).append(i)
    words = []
    for w in re.findall(r"[A-Za-z']+", text or ""):
        found = by_word.pop(_norm(w), None)
        if found:
            words.append({"word": w, "score": 40, "error_type": "Mispronunciation",
                          "phonemes": [{"ipa": i.get("expected", "?"), "score": 30, "heard": i.get("heard") or None} for i in found]})
        else:
            words.append({"word": w, "score": 95, "error_type": "None", "phonemes": []})
    try:
        overall = float(p.get("overall"))
    except (TypeError, ValueError):
        overall = None
    notes = [f"{i['word']}: /{i.get('expected', '?')}/ → /{i.get('heard', '?')}/. {i.get('tip', '')}".strip() for i in issues]
    if p.get("intonation"):
        notes.append(str(p["intonation"]))
    return {
        "provider": "audio_llm", "approximate": True,
        "reference": text, "recognized": text,
        "overall": overall if overall is not None else 0, "accuracy": overall if overall is not None else 0,
        "fluency": None, "prosody": None, "completeness": None,
        "words": words, "notes": notes,
    }


def _norm(w: str) -> str:
    return re.sub(r"[^a-z']", "", w.lower())
