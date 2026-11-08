"""Long-term learner memory: building the context block and applying updates."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone

from ..db import jload, now, rows

PHONEME_EMA = 0.3  # weight of a new observation in recent_avg


def _key(s: str) -> str:
    return re.sub(r"[^a-z0-9а-яё ]+", "", (s or "").lower()).strip()


def get_profile(conn: sqlite3.Connection) -> dict:
    return dict(conn.execute("SELECT * FROM profile WHERE id = 1").fetchone())


def weak_phonemes(conn: sqlite3.Connection, limit: int = 5, min_attempts: int = 3) -> list[dict]:
    out = rows(conn.execute(
        "SELECT * FROM phoneme_stats WHERE attempts >= ? ORDER BY recent_avg ASC LIMIT ?", (min_attempts, limit)))
    for r in out:
        r["substitutions"] = jload(r["substitutions"], {})
        r["examples"] = jload(r["examples"], [])
    return [r for r in out if (r["recent_avg"] or 0) < 85]


def build_context(conn: sqlite3.Connection) -> str:
    p = get_profile(conn)
    lines = []
    if p["level"]:
        lines.append(f"Level: {p['level']} (confidence {p['level_confidence'] or 0:.1f})")
    else:
        lines.append("Level: not assessed yet")
    for label, key in (("Goals", "goals"), ("Interests", "interests"), ("Strengths", "strengths"), ("Weaknesses", "weaknesses")):
        if p[key]:
            lines.append(f"{label}: {p[key]}")
    if p["tutor_notes"]:
        lines.append(f"Tutor notes: {p['tutor_notes']}")

    mistakes = rows(conn.execute(
        "SELECT id, category, pattern, example, correction, count, status FROM mistakes "
        "WHERE status != 'mastered' ORDER BY count DESC, last_seen DESC LIMIT 8"))
    if mistakes:
        lines.append("Recurring mistakes (id, pattern, count, status, example -> correction):")
        for m in mistakes:
            lines.append(f"  #{m['id']} [{m['category']}] {m['pattern']} x{m['count']} {m['status']}: "
                         f"\"{m['example']}\" -> \"{m['correction']}\"")

    weak = weak_phonemes(conn)
    if weak:
        lines.append("Weak sounds: " + "; ".join(
            f"/{w['phoneme']}/ avg {w['recent_avg']:.0f}"
            + (f", often sounds like /{max(w['substitutions'], key=w['substitutions'].get)}/" if w["substitutions"] else "")
            + (f" (e.g. {', '.join(w['examples'][:3])})" if w["examples"] else "")
            for w in weak))

    due = rows(conn.execute(
        "SELECT word FROM vocab WHERE due IS NULL OR due <= ? ORDER BY due LIMIT 10", (now(),)))
    if due:
        lines.append("Vocabulary to recycle in conversation: " + ", ".join(d["word"] for d in due))

    sessions = rows(conn.execute(
        "SELECT mode, topic, started_at, summary FROM sessions WHERE summary IS NOT NULL ORDER BY id DESC LIMIT 3"))
    if sessions:
        lines.append("Recent sessions (newest first):")
        for s in sessions:
            lines.append(f"  {s['started_at'][:10]} {s['mode']}{(' / ' + s['topic']) if s['topic'] else ''}: {s['summary']}")
    return "\n".join(lines)


def apply_turn(conn: sqlite3.Connection, data: dict, user_text: str) -> list[dict]:
    """Store corrections and new vocabulary from a tutor turn. Returns corrections with mistake ids."""
    ts = now()
    out = []
    for c in (data.get("corrections") or [])[:5]:
        if not isinstance(c, dict) or not c.get("corrected"):
            continue
        pattern = (c.get("pattern") or c.get("category") or "other").strip()[:120]
        key = _key(pattern) or _key(c.get("corrected", ""))
        existing = conn.execute("SELECT id, status FROM mistakes WHERE pattern_key = ?", (key,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE mistakes SET count = count + 1, last_seen = ?, example = ?, correction = ?, explanation = ?, "
                "status = CASE WHEN status = 'mastered' THEN 'active' ELSE status END WHERE id = ?",
                (ts, c.get("original", ""), c["corrected"], c.get("explanation", ""), existing["id"]))
            mid = existing["id"]
        else:
            cur = conn.execute(
                "INSERT INTO mistakes (category, pattern, pattern_key, example, correction, explanation, first_seen, last_seen) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (c.get("category", "grammar"), pattern, key, c.get("original", ""), c["corrected"],
                 c.get("explanation", ""), ts, ts))
            mid = cur.lastrowid
        out.append({**c, "mistake_id": mid})
    for v in (data.get("new_vocab") or [])[:5]:
        if isinstance(v, dict) and v.get("word"):
            add_vocab(conn, v["word"], v.get("translation", ""), v.get("context", ""))
    return out


def add_vocab(conn: sqlite3.Connection, word: str, translation: str = "", context: str = "") -> None:
    conn.execute(
        "INSERT INTO vocab (word, word_key, translation, context, due, added_at) VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(word_key) DO NOTHING",
        (word.strip(), _key(word), translation, context, now(), now()))


def record_pron(conn: sqlite3.Connection, session_id: int | None, res: dict) -> None:
    conn.execute(
        "INSERT INTO pron_attempts (session_id, reference, provider, overall, accuracy, fluency, prosody, detail, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (session_id, res.get("reference"), res.get("provider"), res.get("overall"), res.get("accuracy"),
         res.get("fluency"), res.get("prosody"), json.dumps(res.get("words", []), ensure_ascii=False), now()))
    if res.get("approximate"):  # chat-model scores are not calibrated: keep them out of phoneme stats
        return
    for w in res.get("words", []):
        if w.get("error_type") == "Insertion":
            continue
        for ph in w.get("phonemes", []):
            ipa = (ph.get("ipa") or "").strip()
            if not ipa:
                continue
            score = float(ph.get("score") or 0)
            row = conn.execute("SELECT * FROM phoneme_stats WHERE phoneme = ?", (ipa,)).fetchone()
            subs = jload(row["substitutions"], {}) if row else {}
            examples = jload(row["examples"], []) if row else []
            if ph.get("heard") and ph["heard"] != ipa:
                subs[ph["heard"]] = subs.get(ph["heard"], 0) + 1
            if score < 60 and w["word"].lower() not in examples:
                examples = ([w["word"].lower()] + examples)[:8]
            if row:
                ema = (1 - PHONEME_EMA) * (row["recent_avg"] if row["recent_avg"] is not None else score) + PHONEME_EMA * score
                conn.execute(
                    "UPDATE phoneme_stats SET attempts = attempts + 1, score_sum = score_sum + ?, recent_avg = ?, "
                    "substitutions = ?, examples = ? WHERE phoneme = ?",
                    (score, ema, json.dumps(subs, ensure_ascii=False), json.dumps(examples, ensure_ascii=False), ipa))
            else:
                conn.execute(
                    "INSERT INTO phoneme_stats (phoneme, attempts, score_sum, recent_avg, substitutions, examples) "
                    "VALUES (?,1,?,?,?,?)",
                    (ipa, score, score, json.dumps(subs, ensure_ascii=False), json.dumps(examples, ensure_ascii=False)))


def sm2(card: dict, quality: int, today: datetime | None = None) -> dict:
    """SM-2 spaced repetition. quality 0..5. Returns updated fields."""
    today = today or datetime.now(timezone.utc)
    ease, interval, reps = float(card.get("ease") or 2.5), float(card.get("interval_days") or 0), int(card.get("reps") or 0)
    if quality < 3:
        reps, interval = 0, 0.007  # ~10 minutes: show again in this session
    else:
        reps += 1
        interval = 1 if reps == 1 else 6 if reps == 2 else round(interval * ease, 1)
    ease = max(1.3, ease + 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    due = (today + timedelta(days=interval)).isoformat(timespec="seconds")
    return {"ease": ease, "interval_days": interval, "reps": reps, "due": due}


def apply_finalize(conn: sqlite3.Connection, session_id: int, data: dict) -> None:
    ts = now()
    conn.execute("UPDATE sessions SET summary = ?, ended_at = ? WHERE id = ?",
                 (data.get("summary", ""), ts, session_id))
    p = get_profile(conn)
    notes = data.get("tutor_notes") or p["tutor_notes"]
    interests = data.get("interests") or p["interests"]
    level = data["level"].upper() if _valid_level(data.get("level")) else p["level"]
    conn.execute("UPDATE profile SET tutor_notes = ?, interests = ?, level = COALESCE(?, level), updated_at = ? WHERE id = 1",
                 (notes, interests, level, ts))
    for u in data.get("mistake_updates") or []:
        if isinstance(u, dict) and u.get("status") in ("active", "improving", "mastered"):
            conn.execute("UPDATE mistakes SET status = ? WHERE id = ?", (u["status"], u.get("id")))
    skills = data.get("skills") or {}
    pron = conn.execute("SELECT AVG(overall) AS a FROM pron_attempts WHERE session_id = ?", (session_id,)).fetchone()["a"]
    if pron is None:  # carry the latest known pronunciation score forward
        last = conn.execute("SELECT pronunciation FROM skill_snapshots WHERE pronunciation IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
        pron = last["pronunciation"] if last else None
    conn.execute(
        "INSERT INTO skill_snapshots (session_id, grammar, vocabulary, fluency, pronunciation, level, created_at) VALUES (?,?,?,?,?,?,?)",
        (session_id, _num(skills.get("grammar")), _num(skills.get("vocabulary")), _num(skills.get("fluency")), pron, level, ts))


def apply_placement(conn: sqlite3.Connection, result: dict) -> None:
    if not isinstance(result, dict):
        return
    level = result["level"].upper() if _valid_level(result.get("level")) else None
    conn.execute(
        "UPDATE profile SET level = COALESCE(?, level), level_confidence = ?, strengths = ?, weaknesses = ?, "
        "interests = CASE WHEN ? != '' THEN ? ELSE interests END, updated_at = ? WHERE id = 1",
        (level, _num(result.get("confidence")) or 0.5, result.get("strengths", ""), result.get("weaknesses", ""),
         result.get("interests", ""), result.get("interests", ""), now()))


def _valid_level(v) -> bool:
    return isinstance(v, str) and v.upper() in ("A1", "A2", "B1", "B2", "C1", "C2")


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
