"""Pronunciation assessment.

Result schema shared by all providers:
{
  "provider": "azure" | "local",
  "reference": str, "recognized": str,
  "overall": 0..100, "accuracy": 0..100, "fluency": 0..100|None, "prosody": 0..100|None, "completeness": 0..100|None,
  "words": [{"word": str, "score": 0..100, "error_type": "None"|"Mispronunciation"|"Omission"|"Insertion",
             "phonemes": [{"ipa": str, "score": 0..100, "heard": str|None}]}]
}
"""
from __future__ import annotations

import asyncio


class PronError(RuntimeError):
    pass


def enabled(settings: dict) -> bool:
    return settings["pron"].get("provider", "none") in ("azure", "local", "audio_llm")


async def assess(wav: bytes, reference: str | None, settings: dict) -> dict:
    p = settings["pron"].get("provider", "none")
    if p == "azure":
        from . import azure
        return await asyncio.to_thread(azure.assess, wav, reference, settings)
    if p == "local":
        if not reference:
            raise PronError("Локальной оценке нужен эталонный текст (распознанная фраза)")
        from . import local_phoneme
        return await asyncio.to_thread(local_phoneme.assess, wav, reference)
    if p == "audio_llm":
        from .. import audio_llm
        res = await audio_llm.analyze(wav, audio_llm.find_profile(settings, settings["pron"].get("llm_profile")), settings, reference)
        return res["pron"]
    raise PronError("Оценка произношения отключена")


def weak_words(res: dict, threshold: float = 70) -> list[dict]:
    return [w for w in res.get("words", []) if (w.get("score") or 0) < threshold or w.get("error_type") not in (None, "None")]


def summarize_for_llm(res: dict) -> str:
    """Compact text the tutor LLM sees next to the user's utterance."""
    if not res:
        return ""
    parts = [f"overall {res.get('overall', 0):.0f}/100"]
    if res.get("fluency") is not None:
        parts.append(f"fluency {res['fluency']:.0f}")
    if res.get("prosody") is not None:
        parts.append(f"intonation {res['prosody']:.0f}")
    issues = []
    for w in weak_words(res)[:6]:
        bad = [p for p in w.get("phonemes", []) if (p.get("score") or 0) < 60]
        ph = ", ".join(f"/{p['ipa']}/" + (f" sounded like /{p['heard']}/" if p.get("heard") else "") for p in bad[:3])
        tag = "" if w.get("error_type") in (None, "None", "Mispronunciation") else f" [{w['error_type']}]"
        issues.append(f"'{w['word']}' {w.get('score', 0):.0f}{tag}" + (f" ({ph})" if ph else ""))
    if res.get("approximate"):
        parts = [f"rough estimate {res.get('overall', 0):.0f}/100 (by ear)"]
    s = "Pronunciation: " + ", ".join(parts)
    if issues:
        s += "; weak words: " + "; ".join(issues)
    if res.get("notes"):
        s += "; listener notes: " + " | ".join(res["notes"][:4])
    return s
