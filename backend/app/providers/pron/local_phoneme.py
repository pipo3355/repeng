"""Offline pronunciation scoring.

What was actually said: wav2vec2 CTC phoneme recognizer (facebook/wav2vec2-lv-60-espeak-cv-ft, IPA output).
What should have been said: g2p_en (CMUdict + neural fallback) -> ARPAbet -> IPA.
Both are aligned phoneme-by-phoneme; substitutions show the accent (e.g. /θ/ heard as /s/).
"""
from __future__ import annotations

import json
import re
import threading

from ...audio import to_float32
from .base import PronError
from .phonemes import arpa_to_ipa, normalize, score_words

MODEL_ID = "facebook/wav2vec2-lv-60-espeak-cv-ft"
_state: dict = {}
_lock = threading.Lock()


def _load():
    with _lock:
        if "model" in _state:
            return _state
        try:
            import torch  # noqa: F401
            from huggingface_hub import hf_hub_download
            from transformers import AutoModelForCTC, Wav2Vec2FeatureExtractor
        except ImportError as e:
            raise PronError("Локальная модель не установлена: pip install -r requirements-local.txt") from e
        _state["fe"] = Wav2Vec2FeatureExtractor.from_pretrained(MODEL_ID)
        _state["model"] = AutoModelForCTC.from_pretrained(MODEL_ID).eval()
        with open(hf_hub_download(MODEL_ID, "vocab.json"), encoding="utf-8") as f:
            vocab = json.load(f)
        _state["id2tok"] = {i: t for t, i in vocab.items()}
        _state["blank"] = vocab.get("<pad>", 0)
        return _state


def _g2p():
    with _lock:
        if "g2p" not in _state:
            try:
                import nltk
                for pkg in ("averaged_perceptron_tagger_eng", "averaged_perceptron_tagger", "cmudict"):
                    try:
                        nltk.download(pkg, quiet=True)
                    except Exception:
                        pass
                from g2p_en import G2p
            except ImportError as e:
                raise PronError("g2p_en не установлен: pip install -r requirements-local.txt") from e
            _state["g2p"] = G2p()
        return _state["g2p"]


def recognize_phonemes(wav: bytes) -> list[str]:
    import torch

    st = _load()
    audio = to_float32(wav)
    inputs = st["fe"](audio, sampling_rate=16000, return_tensors="pt")
    with torch.no_grad():
        logits = st["model"](inputs.input_values).logits[0]
    ids = logits.argmax(dim=-1).tolist()
    out, prev = [], None
    for i in ids:
        if i != prev and i != st["blank"]:
            tok = st["id2tok"].get(i, "")
            if tok and not tok.startswith("<") and tok.strip():
                out.append(normalize(tok))
        prev = i
    return [p for p in out if p]


def reference_phonemes(text: str) -> list[tuple[str, list[str]]]:
    g2p = _g2p()
    result = []
    for word in re.findall(r"[A-Za-z']+", text):
        phones = [arpa_to_ipa(t) for t in g2p(word)]
        phones = [p for p in phones if p]
        if phones:
            result.append((word, phones))
    return result


def assess(wav: bytes, reference: str) -> dict:
    ref = reference_phonemes(reference)
    if not ref:
        raise PronError("Пустой эталонный текст")
    hyp = recognize_phonemes(wav)
    words = score_words(ref, hyp)
    all_ph = [p for w in words for p in w["phonemes"]]
    acc = sum(p["score"] for p in all_ph) / len(all_ph) if all_ph else 0
    omitted = sum(1 for w in words if w["error_type"] == "Omission")
    completeness = 100 * (1 - omitted / len(words)) if words else 0
    return {
        "provider": "local",
        "reference": reference,
        "recognized": " ".join(hyp),
        "overall": 0.8 * acc + 0.2 * completeness,
        "accuracy": acc,
        "fluency": None,
        "prosody": None,
        "completeness": completeness,
        "words": words,
    }
