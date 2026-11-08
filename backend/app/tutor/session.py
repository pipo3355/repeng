"""Tutor session flow: start -> turns (text or voice) -> end with memory consolidation."""
from __future__ import annotations

import asyncio
import json
import logging

from .. import settings as st
from ..db import db, jload, now, rows
from ..providers.llm.base import JSONReplyError, LLMError, chat_json, make_llm
from ..providers import audio_llm
from ..providers.pron import base as pron
from ..providers.stt.base import transcribe
from . import memory, prompts

log = logging.getLogger("repeng.session")

HISTORY_LIMIT = 40
DEFAULT_WEAK = [  # typical trouble sounds for Russian speakers, used before we have data
    {"phoneme": "θ", "examples": ["think", "three"]}, {"phoneme": "ð", "examples": ["this", "mother"]},
    {"phoneme": "w", "examples": ["what", "would"]}, {"phoneme": "æ", "examples": ["cat", "bad"]},
    {"phoneme": "ɪ", "examples": ["ship", "live"]}, {"phoneme": "ŋ", "examples": ["thing", "singing"]},
]


def _system(mode: str, topic: str, s: dict) -> str:
    with db() as conn:
        profile = memory.get_profile(conn)
        mem = memory.build_context(conn)
    lang = prompts.LANG_NAMES.get(s["tutor"].get("explain_lang", "ru"), "Russian")
    common = dict(native=profile["native_lang"] or "Russian", explain_lang=lang, memory=mem or "(nothing yet)")
    if mode == "placement":
        return prompts.fill(prompts.PLACEMENT, **common)
    topic_line = f"Today's topic / role-play requested by the learner: {topic}" if topic else \
        "No topic chosen: pick something engaging based on their interests or continue a thread from recent sessions."
    return prompts.fill(prompts.CONVERSATION, level_style=prompts.LEVEL_STYLE.get(profile["level"], prompts.LEVEL_STYLE[None]),
                        topic_line=topic_line, **common)


def _history(conn, session_id: int) -> list[dict]:
    msgs = rows(conn.execute(
        "SELECT role, content, meta FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?", (session_id, HISTORY_LIMIT)))
    out = []
    for m in reversed(msgs):
        content = m["content"]
        meta = jload(m["meta"], {})
        if m["role"] == "user" and meta.get("pron_note"):
            content += f"\n[{meta['pron_note']}]"
        out.append({"role": m["role"], "content": content})
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out


def _add_message(conn, session_id: int, role: str, content: str, meta: dict | None = None) -> int:
    return conn.execute(
        "INSERT INTO messages (session_id, role, content, meta, created_at) VALUES (?,?,?,?,?)",
        (session_id, role, content, json.dumps(meta or {}, ensure_ascii=False), now())).lastrowid


def _reply_data(raw: dict | str) -> dict:
    if isinstance(raw, dict) and raw.get("reply"):
        return raw
    return {"reply": str(raw), "corrections": [], "new_vocab": []}


async def _llm_turn(session_id: int, mode: str, topic: str) -> dict:
    s = st.load()
    llm = make_llm(st.get_profile(s))
    system = _system(mode, topic, s)
    with db() as conn:
        history = _history(conn, session_id)
    try:
        data = await chat_json(llm, system, history, max_tokens=1500)
    except JSONReplyError as e:  # model ignored the format: use its text as the reply
        data = {"reply": e.raw.strip()}
    return _reply_data(data)


async def start(mode: str, topic: str = "") -> dict:
    with db() as conn:
        sid = conn.execute("INSERT INTO sessions (mode, topic, started_at) VALUES (?,?,?)",
                           (mode, topic, now())).lastrowid
        opener = ("(The learner has just opened the placement test. Greet them briefly, explain in one sentence what will happen, and ask the first easy question.)"
                  if mode == "placement" else
                  "(The learner has just started a new conversation session. Greet them, refer to something from memory if available, and start the conversation.)")
        _add_message(conn, sid, "user", opener, {"hidden": True})
    data = await _llm_turn(sid, mode, topic)
    with db() as conn:
        memory.apply_turn(conn, {"new_vocab": data.get("new_vocab")}, "")
        _add_message(conn, sid, "assistant", data["reply"], {})
    return {"session_id": sid, "mode": mode, "reply": data["reply"]}


async def analyze_voice(s: dict, wav: bytes, transcript: str = "", reference: str | None = None):
    """Speech -> (transcript, pronunciation result, pronunciation error).

    reference: known target text (drills); otherwise the transcript is used as the reference,
    because it is what the learner *meant* to say - scoring against it exposes the accent.
    """
    stt_p = s["stt"].get("provider", "browser")
    pron_p = s["pron"].get("provider", "none")
    want_notes = s["pron"].get("llm_notes") and pron_p in ("azure", "local")
    pron_res, pron_error, llm_res = None, None, None

    if not transcript and not reference:
        if stt_p == "azure" and pron_p == "azure":  # one unscripted call returns both
            try:
                pron_res = await pron.assess(wav, None, s)
                transcript = pron_res.get("recognized", "")
            except Exception as e:
                pron_error = str(e)
        elif stt_p == "audio_llm":
            llm_res = await audio_llm.analyze(wav, audio_llm.find_profile(s, s["stt"].get("llm_profile")), s)
            transcript = llm_res["transcript"]
            # the STT call already contains by-ear feedback; reuse it if the same model is configured
            if s["stt"].get("llm_profile") != s["pron"].get("llm_profile"):
                llm_res = None
        if not transcript:
            transcript = await transcribe(s["stt"], wav, s)
    ref = reference or transcript
    if not ref:
        return transcript, None, pron_error

    jobs = {}
    if pron_res is None and pron_p in ("azure", "local"):
        jobs["main"] = pron.assess(wav, ref, s)
    if (pron_p == "audio_llm" or want_notes) and llm_res is None:
        jobs["llm"] = audio_llm.analyze(wav, audio_llm.find_profile(s, s["pron"].get("llm_profile")), s, ref)
    results = dict(zip(jobs, await asyncio.gather(*jobs.values(), return_exceptions=True)))
    for k, v in results.items():
        if isinstance(v, Exception):
            log.warning("pronunciation (%s) failed: %s", k, v)
            pron_error = str(v)
    if isinstance(results.get("main"), dict):
        pron_res = results["main"]
    if isinstance(results.get("llm"), dict):
        llm_res = results["llm"]
    if llm_res:
        if pron_p == "audio_llm":
            pron_res = llm_res["pron"]
        elif pron_res is not None:
            pron_res["notes"] = llm_res["pron"].get("notes", [])
    return transcript, pron_res, pron_error


async def turn(session_id: int, text: str | None, wav: bytes | None) -> dict:
    s = st.load()
    with db() as conn:
        sess = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not sess:
        raise LLMError("Сессия не найдена")
    if sess["ended_at"]:
        raise LLMError("Сессия уже завершена")

    transcript = (text or "").strip()
    pron_res, pron_error = None, None
    if wav:
        transcript, pron_res, pron_error = await analyze_voice(s, wav, transcript)

    if not transcript:
        return {"transcript": "", "error": "Не удалось распознать речь, попробуйте ещё раз."}

    meta = {}
    if pron_res:
        meta["pron_note"] = pron.summarize_for_llm(pron_res)
        meta["pron"] = pron_res
    with db() as conn:
        user_msg_id = _add_message(conn, session_id, "user", transcript, meta)
        if pron_res:
            memory.record_pron(conn, session_id, pron_res)

    data = await _llm_turn(session_id, sess["mode"], sess["topic"])
    with db() as conn:
        corrections = memory.apply_turn(conn, data, transcript)
        meta["corrections"] = corrections
        conn.execute("UPDATE messages SET meta = ? WHERE id = ?", (json.dumps(meta, ensure_ascii=False), user_msg_id))
        _add_message(conn, session_id, "assistant", data["reply"], {"pron_tip": data.get("pron_tip", "")})

    result = {
        "transcript": transcript,
        "pron": pron_res,
        "pron_error": pron_error,
        "reply": data["reply"],
        "corrections": corrections,
        "new_vocab": data.get("new_vocab") or [],
        "pron_tip": data.get("pron_tip") or "",
    }
    if sess["mode"] == "placement" and data.get("placement_done"):
        with db() as conn:
            memory.apply_placement(conn, data.get("placement_result") or {})
        result["placement_result"] = data.get("placement_result")
        result["ended"] = True
        result["summary"] = await end(session_id)
    return result


async def end(session_id: int) -> str:
    with db() as conn:
        sess = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not sess or sess["summary"]:
            return sess["summary"] if sess else ""
        msgs = rows(conn.execute("SELECT role, content, meta FROM messages WHERE session_id = ? ORDER BY id", (session_id,)))
        user_turns = [m for m in msgs if m["role"] == "user" and not jload(m["meta"], {}).get("hidden")]
        if not user_turns:
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            return ""
        mem = memory.build_context(conn)
    lines = []
    for m in msgs:
        meta = jload(m["meta"], {})
        if meta.get("hidden"):
            continue
        who = "Learner" if m["role"] == "user" else "Tutor"
        line = f"{who}: {m['content']}"
        if meta.get("corrections"):
            line += "  {corrections: " + "; ".join(f"{c.get('original')} -> {c.get('corrected')}" for c in meta["corrections"]) + "}"
        if meta.get("pron_note"):
            line += f"  [{meta['pron_note']}]"
        lines.append(line)
    s = st.load()
    lang = prompts.LANG_NAMES.get(s["tutor"].get("explain_lang", "ru"), "Russian")
    system = prompts.fill(prompts.FINALIZE, explain_lang=lang, memory=mem, mode=sess["mode"], transcript="\n".join(lines))
    try:
        llm = make_llm(st.get_profile(s, background=True))
        data = await chat_json(llm, "You are a precise assistant that outputs JSON only.",
                               [{"role": "user", "content": system}], max_tokens=1500)
    except LLMError as e:
        log.warning("finalize failed: %s", e)
        data = {"summary": f"(саммари не создано: {e})"}
    with db() as conn:
        memory.apply_finalize(conn, session_id, data)
    return data.get("summary", "")


async def drill_items(n: int = 5) -> list[dict]:
    s = st.load()
    with db() as conn:
        weak = memory.weak_phonemes(conn, limit=4) or DEFAULT_WEAK[:4]
        profile = memory.get_profile(conn)
    lang = prompts.LANG_NAMES.get(s["tutor"].get("explain_lang", "ru"), "Russian")
    weak_txt = "; ".join(f"/{w['phoneme']}/ (" + ", ".join((w.get("examples") or [])[:4]) + ")" for w in weak)
    prompt = prompts.fill(prompts.DRILL, native=profile["native_lang"] or "Russian", level=profile["level"] or "B1",
                          weak=weak_txt, n=n, explain_lang=lang)
    llm = make_llm(st.get_profile(s, background=True))
    data = await chat_json(llm, "You output JSON only.", [{"role": "user", "content": prompt}], max_tokens=1500)
    return [i for i in data.get("items", []) if isinstance(i, dict) and i.get("text")]


async def drill_assess(wav: bytes, reference: str) -> dict:
    s = st.load()
    if not pron.enabled(s):
        raise pron.PronError("Оценка произношения отключена (Настройки)")
    _, res, err = await analyze_voice(s, wav, reference=reference)
    if res is None:
        raise pron.PronError(err or "Не удалось оценить произношение")
    with db() as conn:
        memory.record_pron(conn, None, res)
    return res


async def exercises() -> list[dict]:
    s = st.load()
    with db() as conn:
        ms = rows(conn.execute(
            "SELECT id, category, pattern, example, correction FROM mistakes WHERE status != 'mastered' "
            "ORDER BY count DESC, last_seen DESC LIMIT 6"))
        profile = memory.get_profile(conn)
    if not ms:
        return []
    lang = prompts.LANG_NAMES.get(s["tutor"].get("explain_lang", "ru"), "Russian")
    txt = "\n".join(f"id={m['id']} [{m['category']}] {m['pattern']}: \"{m['example']}\" -> \"{m['correction']}\"" for m in ms)
    prompt = prompts.fill(prompts.EXERCISES, level=profile["level"] or "B1", mistakes=txt, explain_lang=lang)
    llm = make_llm(st.get_profile(s, background=True))
    data = await chat_json(llm, "You output JSON only.", [{"role": "user", "content": prompt}], max_tokens=2000)
    return [i for i in data.get("items", []) if isinstance(i, dict) and i.get("task")]
