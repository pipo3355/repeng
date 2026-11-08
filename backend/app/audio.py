"""WAV helpers. The browser always sends 16 kHz mono 16-bit PCM WAV."""
from __future__ import annotations

import io
import wave


def read_pcm(wav_bytes: bytes) -> tuple[bytes, int, int, int]:
    """Return (frames, sample_rate, channels, sample_width)."""
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        return w.readframes(w.getnframes()), w.getframerate(), w.getnchannels(), w.getsampwidth()


def duration(wav_bytes: bytes) -> float:
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        return w.getnframes() / float(w.getframerate() or 1)


def to_float32(wav_bytes: bytes):
    """numpy float32 mono array at the file's sample rate (requires numpy)."""
    import numpy as np

    frames, sr, ch, sw = read_pcm(wav_bytes)
    if sw != 2:
        raise ValueError("expected 16-bit PCM")
    a = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    if sr != 16000:
        # simple linear resample; the browser already sends 16 kHz so this is rare
        n = int(len(a) * 16000 / sr)
        a = np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a).astype(np.float32)
    return a
