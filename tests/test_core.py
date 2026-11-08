import sqlite3
from datetime import datetime, timezone

import pytest

from backend.app import db as dbm
from backend.app.providers.llm.base import extract_json
from backend.app.providers.pron.base import summarize_for_llm
from backend.app.providers.pron.phonemes import align, arpa_to_ipa, score_words, split_ipa
from backend.app.tutor import memory, prompts


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    dbm.init(c)
    yield c
    c.close()


# ---- JSON parsing of messy model output ----

def test_extract_json_plain():
    assert extract_json('{"reply": "hi"}') == {"reply": "hi"}


def test_extract_json_fenced_with_chatter():
    text = 'Sure! Here you go:\n```json\n{"reply": "Hello {friend}", "corrections": []}\n```\nAnything else?'
    assert extract_json(text)["reply"] == "Hello {friend}"


def test_extract_json_trailing_comma_and_prefix():
    assert extract_json('Answer: {"a": [1, 2,], "b": "x",}') == {"a": [1, 2], "b": "x"}


def test_extract_json_fails_on_text():
    with pytest.raises(ValueError):
        extract_json("I think you did great today!")


# ---- prompts ----

def test_prompt_fill_keeps_json_braces():
    out = prompts.fill(prompts.CONVERSATION, native="Russian", explain_lang="Russian", memory="M",
                       level_style="L", topic_line="T")
    assert '"reply"' in out and "{explain_lang}" not in out and "{memory}" not in out
    out2 = prompts.fill(prompts.PLACEMENT, native="Russian", explain_lang="Russian", memory="M")
    assert '"placement_done"' in out2 and "{{" not in out2


# ---- phonemes ----

def test_arpa_to_ipa():
    assert arpa_to_ipa("TH") == "θ"
    assert arpa_to_ipa("AH0") == "ə"
    assert arpa_to_ipa("AH1") == "ʌ"
    assert arpa_to_ipa("IY1") == "i"


def test_split_ipa_multichar_and_length():
    assert split_ipa("θ ɪ ŋ k") == ["θ", "ɪ", "ŋ", "k"]
    assert split_ipa("tʃiːz") == ["tʃ", "i", "z"]
    assert split_ipa("aɪ") == ["aɪ"]


def test_align_substitution_th_to_s():
    ops = align(["θ", "ɪ", "ŋ", "k"], ["s", "ɪ", "ŋ", "k"])
    assert ops[0] == ("θ", "s")
    assert all(r == h for r, h in ops[1:])


def test_score_words_marks_accent_error():
    ref = [("think", ["θ", "ɪ", "ŋ", "k"]), ("so", ["s", "oʊ"])]
    words = score_words(ref, ["s", "ɪ", "ŋ", "k", "s", "oʊ"])
    think, so = words
    assert think["phonemes"][0] == {"ipa": "θ", "score": 20, "heard": "s"}
    assert think["score"] < 100 and so["score"] == 100


def test_score_words_omission():
    words = score_words([("very", ["v", "ɛ", "ɹ", "i"]), ("good", ["ɡ", "ʊ", "d"])], ["ɡ", "ʊ", "d"])
    assert words[0]["error_type"] == "Omission"
    assert words[1]["score"] == 100


# ---- memory ----

def test_apply_turn_dedupes_mistakes_and_vocab(conn):
    turn = {"corrections": [{"original": "I go yesterday", "corrected": "I went yesterday", "category": "tense",
                             "pattern": "Past simple for finished actions", "explanation": "..."}],
            "new_vocab": [{"word": "commute", "translation": "дорога на работу"}]}
    memory.apply_turn(conn, turn, "I go yesterday")
    memory.apply_turn(conn, turn, "I go yesterday")
    m = conn.execute("SELECT * FROM mistakes").fetchall()
    assert len(m) == 1 and m[0]["count"] == 2
    assert conn.execute("SELECT COUNT(*) FROM vocab").fetchone()[0] == 1


def test_record_pron_updates_phoneme_stats(conn):
    res = {"provider": "local", "reference": "think", "overall": 60, "accuracy": 60,
           "words": [{"word": "think", "score": 60, "error_type": "Mispronunciation",
                      "phonemes": [{"ipa": "θ", "score": 20, "heard": "s"}, {"ipa": "ɪ", "score": 100, "heard": None}]}]}
    for _ in range(3):
        memory.record_pron(conn, None, res)
    th = conn.execute("SELECT * FROM phoneme_stats WHERE phoneme='θ'").fetchone()
    assert th["attempts"] == 3 and th["recent_avg"] == pytest.approx(20)
    weak = memory.weak_phonemes(conn)
    assert weak[0]["phoneme"] == "θ" and weak[0]["substitutions"] == {"s": 3} and "think" in weak[0]["examples"]


def test_build_context_includes_memory(conn):
    memory.apply_turn(conn, {"corrections": [{"original": "a", "corrected": "b", "pattern": "articles", "category": "article"}]}, "a")
    conn.execute("UPDATE profile SET level='B1', interests='football'")
    ctx = memory.build_context(conn)
    assert "B1" in ctx and "football" in ctx and "articles" in ctx


def test_finalize_and_placement(conn):
    sid = conn.execute("INSERT INTO sessions (mode, started_at) VALUES ('placement', ?)", (dbm.now(),)).lastrowid
    memory.apply_placement(conn, {"level": "b2", "confidence": 0.8, "strengths": "vocab", "weaknesses": "articles"})
    memory.apply_finalize(conn, sid, {"summary": "ok", "tutor_notes": "likes games", "skills": {"grammar": 70},
                                      "level": "B2", "mistake_updates": []})
    p = memory.get_profile(conn)
    assert p["level"] == "B2" and p["tutor_notes"] == "likes games"
    snap = conn.execute("SELECT * FROM skill_snapshots").fetchone()
    assert snap["grammar"] == 70


def test_sm2_progression():
    t = datetime(2026, 1, 1, tzinfo=timezone.utc)
    c = {"ease": 2.5, "interval_days": 0, "reps": 0}
    c1 = memory.sm2(c, 4, t)
    assert c1["interval_days"] == 1
    c2 = memory.sm2(c1, 5, t)
    assert c2["interval_days"] == 6
    c3 = memory.sm2(c2, 4, t)
    assert c3["interval_days"] > 6
    fail = memory.sm2(c3, 1, t)
    assert fail["reps"] == 0 and fail["interval_days"] < 1 and fail["ease"] < c3["ease"]


def test_pron_summary_for_llm():
    res = {"overall": 62, "fluency": 80, "prosody": None,
           "words": [{"word": "think", "score": 40, "error_type": "Mispronunciation",
                      "phonemes": [{"ipa": "θ", "score": 10, "heard": "s"}]}]}
    s = summarize_for_llm(res)
    assert "think" in s and "/θ/ sounded like /s/" in s


def test_audio_llm_schema_mapping():
    from backend.app.providers.audio_llm import to_schema
    res = to_schema({"overall": 70, "issues": [{"word": "Think", "expected": "θ", "heard": "s", "tip": "язык между зубами"}],
                     "intonation": "ровная интонация"}, "I think so")
    assert res["approximate"] and res["overall"] == 70
    think = [w for w in res["words"] if w["word"] == "think"][0]
    assert think["phonemes"][0] == {"ipa": "θ", "score": 30, "heard": "s"}
    assert len(res["notes"]) == 2
    assert "listener notes" in summarize_for_llm(res)


def test_approximate_results_skip_phoneme_stats(conn):
    res = {"provider": "audio_llm", "approximate": True, "overall": 50,
           "words": [{"word": "think", "score": 40, "phonemes": [{"ipa": "θ", "score": 30, "heard": "s"}]}]}
    memory.record_pron(conn, None, res)
    assert conn.execute("SELECT COUNT(*) FROM pron_attempts").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM phoneme_stats").fetchone()[0] == 0


def test_tts_split_by_language():
    from backend.app.providers.tts.base import split_by_language
    parts = split_by_language("Great! What did you do at the weekend (на выходных)? Скажите: I went to the cinema.")
    assert [ru for ru, _ in parts] == [False, True, False]
    assert parts[1][1].startswith("на выходных")
    assert parts[2][1] == "I went to the cinema."
    assert split_by_language("Hello!") == [(False, "Hello!")]


def test_partial_settings_update_keeps_profiles(tmp_path, monkeypatch):
    from backend.app import settings as st
    monkeypatch.setattr(st, "DATA_DIR", tmp_path)
    monkeypatch.setattr(st, "SETTINGS_PATH", tmp_path / "settings.json")
    st.update_from_client({"llm_profiles": [{"id": "a1", "name": "X", "kind": "openai_compat", "api_key": "secret-key-123", "model": "m"}],
                           "azure": {"key": "azkey-456", "region": "westeurope"}})
    st.update_from_client({"tutor": {"voice_english_only": True}})
    s = st.load()
    assert s["tutor"]["voice_english_only"] is True and s["tutor"]["explain_lang"] == "ru"
    assert s["llm_profiles"][0]["api_key"] == "secret-key-123" and s["active_llm"] == "a1"
    assert s["azure"]["key"] == "azkey-456"
