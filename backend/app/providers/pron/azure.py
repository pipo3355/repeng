"""Azure Speech pronunciation assessment (phoneme level, IPA, prosody).

Scripted mode: reference text given -> scores against what the learner meant to say.
Unscripted mode: reference None -> Azure recognizes and scores free speech.
"""
from __future__ import annotations

import json
import threading

from ...audio import read_pcm
from .base import PronError


def assess(wav: bytes, reference: str | None, settings: dict) -> dict:
    try:
        import azure.cognitiveservices.speech as sdk
    except ImportError as e:
        raise PronError("Не установлен azure-cognitiveservices-speech") from e
    az = settings["azure"]
    if not az.get("key") or not az.get("region"):
        raise PronError("Не заданы ключ и регион Azure Speech (Настройки → Azure)")

    frames, sr, ch, sw = read_pcm(wav)
    speech_config = sdk.SpeechConfig(subscription=az["key"], region=az["region"])
    speech_config.speech_recognition_language = settings["tutor"].get("accent") or "en-US"
    fmt = sdk.audio.AudioStreamFormat(samples_per_second=sr, bits_per_sample=sw * 8, channels=ch)
    stream = sdk.audio.PushAudioInputStream(stream_format=fmt)
    stream.write(frames)
    stream.close()
    audio_config = sdk.audio.AudioConfig(stream=stream)

    pa = sdk.PronunciationAssessmentConfig(
        reference_text=reference or "",
        grading_system=sdk.PronunciationAssessmentGradingSystem.HundredMark,
        granularity=sdk.PronunciationAssessmentGranularity.Phoneme,
        enable_miscue=bool(reference),
    )
    pa.phoneme_alphabet = "IPA"
    pa.nbest_phoneme_count = 3
    try:
        pa.enable_prosody_assessment()
    except Exception:
        pass

    recognizer = sdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)
    pa.apply_to(recognizer)

    segments: list[dict] = []
    errors: list[str] = []
    done = threading.Event()

    def on_recognized(evt):
        if evt.result.reason == sdk.ResultReason.RecognizedSpeech:
            raw = evt.result.properties.get(sdk.PropertyId.SpeechServiceResponse_JsonResult)
            if raw:
                segments.append(json.loads(raw))

    def on_canceled(evt):
        d = evt.cancellation_details
        if d.reason == sdk.CancellationReason.Error:
            errors.append(f"{d.error_code}: {d.error_details}")
        done.set()

    recognizer.recognized.connect(on_recognized)
    recognizer.canceled.connect(on_canceled)
    recognizer.session_stopped.connect(lambda evt: done.set())
    recognizer.start_continuous_recognition()
    done.wait(timeout=90)
    recognizer.stop_continuous_recognition()

    if errors and not segments:
        raise PronError("Azure: " + errors[0])
    return _parse(segments, reference)


def _parse(segments: list[dict], reference: str | None) -> dict:
    words, texts = [], []
    totals = {"accuracy": [], "fluency": [], "prosody": [], "completeness": [], "overall": []}
    for seg in segments:
        nb = (seg.get("NBest") or [{}])[0]
        texts.append(nb.get("Display") or seg.get("DisplayText") or "")
        pa = nb.get("PronunciationAssessment") or {}
        n = max(1, len(nb.get("Words") or []))
        for key, src in (("accuracy", "AccuracyScore"), ("fluency", "FluencyScore"), ("prosody", "ProsodyScore"),
                         ("completeness", "CompletenessScore"), ("overall", "PronScore")):
            if src in pa:
                totals[key].append((pa[src], n))
        for w in nb.get("Words") or []:
            wpa = w.get("PronunciationAssessment") or {}
            phonemes = []
            for ph in w.get("Phonemes") or []:
                ppa = ph.get("PronunciationAssessment") or {}
                score = ppa.get("AccuracyScore", 0)
                heard = None
                nbest = ppa.get("NBestPhonemes") or []
                if nbest and nbest[0].get("Phoneme") and nbest[0]["Phoneme"] != ph.get("Phoneme") and score < 60:
                    heard = nbest[0]["Phoneme"]
                phonemes.append({"ipa": ph.get("Phoneme", ""), "score": score, "heard": heard})
            words.append({
                "word": w.get("Word", ""),
                "score": wpa.get("AccuracyScore", 0),
                "error_type": wpa.get("ErrorType", "None"),
                "phonemes": phonemes,
            })

    def avg(key):
        vals = totals[key]
        if not vals:
            return None
        return sum(v * n for v, n in vals) / sum(n for _, n in vals)

    acc = avg("accuracy")
    return {
        "provider": "azure",
        "reference": reference or " ".join(texts),
        "recognized": " ".join(t for t in texts if t).strip(),
        "overall": avg("overall") if avg("overall") is not None else (acc or 0),
        "accuracy": acc or 0,
        "fluency": avg("fluency"),
        "prosody": avg("prosody"),
        "completeness": avg("completeness"),
        "words": words,
    }
