"""RepEng - AI English tutor. Run: uvicorn backend.app.main:app"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db as dbm
from . import settings as st
from .db import db, jload, rows
from .providers.llm.base import LLMError, make_llm
from .providers.pron.base import PronError
from .providers.stt.base import STTError, transcribe
from .providers.tts.base import TTSError, synthesize
from .tutor import memory, session

logging.basicConfig(level=logging.INFO)
FRONTEND = Path(__file__).resolve().parents[2] / "frontend"

app = FastAPI(title="RepEng")
dbm.init()


@app.exception_handler(LLMError)
@app.exception_handler(STTError)
@app.exception_handler(TTSError)
@app.exception_handler(PronError)
async def _provider_error(_, exc: Exception):
    return JSONResponse({"detail": str(exc)}, status_code=502)


# ---------- settings ----------

@app.get("/api/settings")
def get_settings():
    return st.public(st.load())


@app.put("/api/settings")
def put_settings(body: dict):
    return st.public(st.update_from_client(body))


class TestReq(BaseModel):
    target: str               # llm | stt | tts | pron
    profile_id: str | None = None


@app.post("/api/settings/test")
async def test_provider(req: TestReq):
    s = st.load()
    if req.target == "llm":
        prof = next((p for p in s["llm_profiles"] if p["id"] == req.profile_id), None)
        text = await make_llm(prof).chat("You are a test endpoint.", [{"role": "user", "content": "Reply with exactly: OK"}], 50)
        return {"ok": True, "message": f"Ответ модели: {text.strip()[:100]}"}
    if req.target == "tts":
        if s["tts"]["provider"] == "browser":
            return {"ok": True, "message": "Используется браузерный синтез"}
        audio, _ = await synthesize("Hello! Let's practise English.", s)
        return {"ok": True, "message": f"Получено {len(audio) // 1024} КБ аудио"}
    if req.target in ("stt", "pron"):
        import io, math, struct, wave
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:  # 1 s of quiet tone - checks credentials/connectivity only
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
            w.writeframes(b"".join(struct.pack("<h", int(800 * math.sin(i / 8))) for i in range(16000)))
        wav = buf.getvalue()
        if req.target == "stt":
            if s["stt"]["provider"] == "browser":
                return {"ok": True, "message": "Используется браузерное распознавание (Chrome/Edge)"}
            text = await transcribe(s["stt"], wav, s)
            return {"ok": True, "message": f"Сервис принял аудио (в тестовом сигнале нет речи, распознано: «{text}»)"}
        if s["pron"]["provider"] == "audio_llm" or (s["pron"].get("llm_notes") and s["pron"]["provider"] != "none"):
            from .providers import audio_llm
            prof = audio_llm.find_profile(s, s["pron"].get("llm_profile"))
            r = await audio_llm.analyze(wav, prof, s, "hello")
            msg = f"Аудио-модель {prof.get('model')} приняла запись (оценка {r['pron']['overall']:.0f})"
            if s["pron"]["provider"] == "audio_llm":
                return {"ok": True, "message": msg}
        else:
            msg = ""
        if s["pron"]["provider"] == "local":
            from .providers.pron import local_phoneme
            import asyncio
            await asyncio.to_thread(local_phoneme._load)
            await asyncio.to_thread(local_phoneme._g2p)
            return {"ok": True, "message": "Локальная модель загружена" + ("; " + msg if msg else "")}
        if s["pron"]["provider"] == "azure":
            from .providers.pron.base import assess
            await assess(wav, "hello", s)
            return {"ok": True, "message": "Azure ответил" + ("; " + msg if msg else "")}
        return {"ok": True, "message": "Оценка произношения выключена"}
    raise HTTPException(400, "unknown target")


# ---------- sessions ----------

class StartReq(BaseModel):
    mode: str = "conversation"   # conversation | placement
    topic: str = ""


@app.post("/api/session/start")
async def start_session(req: StartReq):
    if req.mode not in ("conversation", "placement"):
        raise HTTPException(400, "bad mode")
    return await session.start(req.mode, req.topic)


@app.post("/api/session/{sid}/turn")
async def session_turn(sid: int, text: str = Form(""), audio: UploadFile | None = File(None)):
    wav = await audio.read() if audio else None
    if not text.strip() and not wav:
        raise HTTPException(400, "empty turn")
    return await session.turn(sid, text, wav)


@app.post("/api/session/{sid}/end")
async def session_end(sid: int):
    return {"summary": await session.end(sid)}


@app.get("/api/session/{sid}")
def session_get(sid: int):
    with db() as conn:
        s = conn.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
        if not s:
            raise HTTPException(404)
        msgs = rows(conn.execute("SELECT id, role, content, meta, created_at FROM messages WHERE session_id = ? ORDER BY id", (sid,)))
    for m in msgs:
        m["meta"] = jload(m["meta"], {})
    return {"session": dict(s), "messages": [m for m in msgs if not m["meta"].get("hidden")]}


# ---------- pronunciation drills ----------

@app.post("/api/drill/generate")
async def drill_generate(n: int = 5):
    return {"items": await session.drill_items(n)}


@app.post("/api/drill/assess")
async def drill_assess(reference: str = Form(...), audio: UploadFile = File(...)):
    return await session.drill_assess(await audio.read(), reference)


# ---------- review ----------

@app.get("/api/review/vocab")
def review_vocab(limit: int = 20):
    with db() as conn:
        return {"items": rows(conn.execute(
            "SELECT * FROM vocab WHERE due IS NULL OR due <= ? ORDER BY due LIMIT ?", (dbm.now(), limit)))}


class Grade(BaseModel):
    quality: int


@app.post("/api/review/vocab/{vid}")
def grade_vocab(vid: int, g: Grade):
    with db() as conn:
        card = conn.execute("SELECT * FROM vocab WHERE id = ?", (vid,)).fetchone()
        if not card:
            raise HTTPException(404)
        upd = memory.sm2(dict(card), max(0, min(5, g.quality)))
        conn.execute("UPDATE vocab SET ease=?, interval_days=?, reps=?, due=? WHERE id=?",
                     (upd["ease"], upd["interval_days"], upd["reps"], upd["due"], vid))
    return upd


class VocabIn(BaseModel):
    word: str
    translation: str = ""
    context: str = ""


@app.post("/api/vocab")
def add_vocab(v: VocabIn):
    with db() as conn:
        memory.add_vocab(conn, v.word, v.translation, v.context)
    return {"ok": True}


@app.delete("/api/vocab/{vid}")
def del_vocab(vid: int):
    with db() as conn:
        conn.execute("DELETE FROM vocab WHERE id = ?", (vid,))
    return {"ok": True}


@app.post("/api/review/exercises")
async def review_exercises():
    return {"items": await session.exercises()}


class ExerciseResult(BaseModel):
    correct: bool


@app.post("/api/review/mistake/{mid}")
def mistake_result(mid: int, r: ExerciseResult):
    with db() as conn:
        if r.correct:
            conn.execute("UPDATE mistakes SET status = CASE WHEN status='improving' THEN 'mastered' "
                         "WHEN status='active' THEN 'improving' ELSE status END WHERE id = ?", (mid,))
        else:
            conn.execute("UPDATE mistakes SET status='active', count=count+1, last_seen=? WHERE id = ?", (dbm.now(), mid))
    return {"ok": True}


# ---------- progress & profile ----------

@app.get("/api/progress")
def progress():
    with db() as conn:
        profile = memory.get_profile(conn)
        snapshots = rows(conn.execute("SELECT * FROM skill_snapshots ORDER BY id"))
        mistakes = rows(conn.execute("SELECT * FROM mistakes ORDER BY status='mastered', count DESC LIMIT 30"))
        phonemes = rows(conn.execute("SELECT * FROM phoneme_stats ORDER BY recent_avg ASC"))
        sessions = rows(conn.execute(
            "SELECT s.*, (SELECT COUNT(*) FROM messages m WHERE m.session_id=s.id AND m.role='user') AS turns "
            "FROM sessions s ORDER BY id DESC LIMIT 30"))
        counts = {
            "vocab": conn.execute("SELECT COUNT(*) FROM vocab").fetchone()[0],
            "vocab_due": conn.execute("SELECT COUNT(*) FROM vocab WHERE due <= ?", (dbm.now(),)).fetchone()[0],
            "sessions": conn.execute("SELECT COUNT(*) FROM sessions WHERE ended_at IS NOT NULL").fetchone()[0],
            "pron_attempts": conn.execute("SELECT COUNT(*) FROM pron_attempts").fetchone()[0],
        }
    for p in phonemes:
        p["substitutions"] = jload(p["substitutions"], {})
        p["examples"] = jload(p["examples"], [])
    return {"profile": profile, "snapshots": snapshots, "mistakes": mistakes, "phonemes": phonemes,
            "sessions": sessions, "counts": counts}


class ProfileIn(BaseModel):
    goals: str | None = None
    interests: str | None = None
    native_lang: str | None = None
    level: str | None = None


@app.put("/api/profile")
def put_profile(p: ProfileIn):
    with db() as conn:
        for k, v in p.model_dump(exclude_none=True).items():
            conn.execute(f"UPDATE profile SET {k} = ? WHERE id = 1", (v,))  # keys come from the pydantic model
    return {"ok": True}


@app.get("/api/memory")
def memory_preview():
    """What the tutor currently 'knows' - shown in the progress page."""
    with db() as conn:
        return {"context": memory.build_context(conn)}


# ---------- tts ----------

class TTSReq(BaseModel):
    text: str
    rate: float | None = None


@app.post("/api/tts")
async def tts(req: TTSReq):
    audio, mime = await synthesize(req.text[:2000], st.load(), req.rate)
    return Response(audio, media_type=mime)


# ---------- frontend ----------

app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")
