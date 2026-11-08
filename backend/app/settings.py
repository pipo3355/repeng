"""Provider settings stored in data/settings.json (local file, contains API keys)."""
from __future__ import annotations

import copy
import json
import threading
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
SETTINGS_PATH = DATA_DIR / "settings.json"
MASK = "••••"

LLM_PRESETS = {
    "omniroute": {"name": "OmniRoute", "kind": "openai_compat", "base_url": "http://localhost:20128/v1", "model": ""},
    "openrouter": {"name": "OpenRouter", "kind": "openai_compat", "base_url": "https://openrouter.ai/api/v1", "model": ""},
    "openai": {"name": "OpenAI", "kind": "openai_compat", "base_url": "https://api.openai.com/v1", "model": "gpt-5"},
    "groq": {"name": "Groq", "kind": "openai_compat", "base_url": "https://api.groq.com/openai/v1", "model": "llama-3.3-70b-versatile"},
    "ollama": {"name": "Ollama", "kind": "openai_compat", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
    "lmstudio": {"name": "LM Studio", "kind": "openai_compat", "base_url": "http://localhost:1234/v1", "model": ""},
    "anthropic": {"name": "Anthropic", "kind": "anthropic", "base_url": "", "model": "claude-opus-5-5"},
    "custom": {"name": "Custom", "kind": "openai_compat", "base_url": "", "model": ""},
}

DEFAULTS: dict = {
    "llm_profiles": [],          # [{id,name,kind,base_url,api_key,model,headers,effort,fallbacks}]
    "active_llm": None,
    "background_llm": None,      # None -> use active
    "stt": {"provider": "browser", "base_url": "https://api.groq.com/openai/v1", "api_key": "",
            "model": "whisper-large-v3-turbo", "local_model": "small.en", "llm_profile": None},
    "tts": {"provider": "browser", "base_url": "https://api.openai.com/v1", "api_key": "",
            "model": "gpt-4o-mini-tts", "voice": "alloy", "azure_voice": "en-US-AvaMultilingualNeural", "azure_ru_voice": "ru-RU-SvetlanaNeural", "rate": 1.0},
    "pron": {"provider": "none", "llm_notes": False, "llm_profile": None},  # provider: none | azure | local | audio_llm
    "azure": {"key": "", "region": ""},
    "tutor": {"explain_lang": "ru", "accent": "en-US", "voice_english_only": False},
}

SECRET_PATHS = [("stt", "api_key"), ("tts", "api_key"), ("azure", "key")]

_lock = threading.Lock()


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load() -> dict:
    with _lock:
        if SETTINGS_PATH.exists():
            try:
                return _merge(DEFAULTS, json.loads(SETTINGS_PATH.read_text("utf-8")))
            except json.JSONDecodeError:
                pass
        return copy.deepcopy(DEFAULTS)


def save(s: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    with _lock:
        tmp = SETTINGS_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(s, ensure_ascii=False, indent=2), "utf-8")
        tmp.replace(SETTINGS_PATH)


def _mask(v: str) -> str:
    return (MASK + v[-4:]) if v else ""


def public(s: dict) -> dict:
    """Copy with secrets masked, safe to send to the browser."""
    p = copy.deepcopy(s)
    for prof in p["llm_profiles"]:
        prof["api_key"] = _mask(prof.get("api_key", ""))
    for sec, key in SECRET_PATHS:
        p[sec][key] = _mask(p[sec].get(key, ""))
    p["presets"] = LLM_PRESETS
    return p


def update_from_client(new: dict) -> dict:
    """Apply settings coming from the UI; masked secrets keep their stored values."""
    cur = load()
    new = copy.deepcopy(new)
    new.pop("presets", None)
    old_profiles = {p["id"]: p for p in cur["llm_profiles"]}
    for prof in new.get("llm_profiles", []):
        prof.setdefault("id", uuid.uuid4().hex[:8])
        if not prof["id"]:
            prof["id"] = uuid.uuid4().hex[:8]
        if str(prof.get("api_key", "")).startswith(MASK):
            prof["api_key"] = old_profiles.get(prof["id"], {}).get("api_key", "")
    for sec, key in SECRET_PATHS:
        if sec in new and str(new[sec].get(key, "")).startswith(MASK):
            new[sec][key] = cur[sec].get(key, "")
    merged = _merge(cur, new)
    if "llm_profiles" in new:
        merged["llm_profiles"] = new["llm_profiles"]
    ids = {p["id"] for p in merged["llm_profiles"]}
    if merged["active_llm"] not in ids:
        merged["active_llm"] = next(iter(ids), None)
    if merged["background_llm"] not in ids:
        merged["background_llm"] = None
    save(merged)
    return merged


def get_profile(s: dict, background: bool = False) -> dict | None:
    pid = (s.get("background_llm") if background else None) or s.get("active_llm")
    for p in s["llm_profiles"]:
        if p["id"] == pid:
            return p
    return s["llm_profiles"][0] if s["llm_profiles"] else None
