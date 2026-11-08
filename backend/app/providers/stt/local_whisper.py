"""Offline transcription with faster-whisper (pip install -r requirements-local.txt)."""
from __future__ import annotations

import threading

from ...audio import to_float32

_models: dict = {}
_lock = threading.Lock()


def _get(name: str):
    with _lock:
        if name not in _models:
            try:
                from faster_whisper import WhisperModel
            except ImportError as e:
                raise RuntimeError("faster-whisper не установлен: pip install -r requirements-local.txt") from e
            _models[name] = WhisperModel(name, device="auto", compute_type="int8")
        return _models[name]


def transcribe(wav: bytes, model_name: str = "small.en") -> str:
    model = _get(model_name)
    segments, _ = model.transcribe(to_float32(wav), language="en", beam_size=5, vad_filter=True)
    return " ".join(s.text.strip() for s in segments).strip()
