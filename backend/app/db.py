"""SQLite storage for learner memory and progress."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from .settings import DATA_DIR

DB_PATH = DATA_DIR / "repeng.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    level TEXT,                 -- CEFR: A1..C2, NULL until placement
    level_confidence REAL,
    goals TEXT DEFAULT '',
    interests TEXT DEFAULT '',
    native_lang TEXT DEFAULT 'Russian',
    tutor_notes TEXT DEFAULT '',
    strengths TEXT DEFAULT '',
    weaknesses TEXT DEFAULT '',
    updated_at TEXT
);
INSERT OR IGNORE INTO profile (id) VALUES (1);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mode TEXT NOT NULL,         -- placement | conversation
    topic TEXT DEFAULT '',
    started_at TEXT NOT NULL,
    ended_at TEXT,
    summary TEXT,
    metrics TEXT                -- JSON
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,         -- user | assistant
    content TEXT NOT NULL,
    meta TEXT,                  -- JSON: corrections, pron, ...
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mistakes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    pattern TEXT NOT NULL,
    pattern_key TEXT NOT NULL UNIQUE,
    example TEXT,
    correction TEXT,
    explanation TEXT,
    count INTEGER DEFAULT 1,
    status TEXT DEFAULT 'active',  -- active | improving | mastered
    first_seen TEXT,
    last_seen TEXT
);

CREATE TABLE IF NOT EXISTS vocab (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word TEXT NOT NULL,
    word_key TEXT NOT NULL UNIQUE,
    translation TEXT,
    context TEXT,
    ease REAL DEFAULT 2.5,
    interval_days REAL DEFAULT 0,
    reps INTEGER DEFAULT 0,
    due TEXT,
    added_at TEXT
);

CREATE TABLE IF NOT EXISTS pron_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    reference TEXT,
    provider TEXT,
    overall REAL,
    accuracy REAL,
    fluency REAL,
    prosody REAL,
    detail TEXT,                -- JSON
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS phoneme_stats (
    phoneme TEXT PRIMARY KEY,
    attempts INTEGER DEFAULT 0,
    score_sum REAL DEFAULT 0,
    recent_avg REAL,            -- exponential moving average, reflects improvement
    substitutions TEXT DEFAULT '{}',  -- JSON {heard: count}
    examples TEXT DEFAULT '[]'        -- JSON list of words
);

CREATE TABLE IF NOT EXISTS skill_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    grammar REAL, vocabulary REAL, fluency REAL, pronunciation REAL,
    level TEXT,
    created_at TEXT
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init(conn: sqlite3.Connection | None = None) -> None:
    if conn is None:
        with db() as c:
            c.executescript(SCHEMA)
    else:
        conn.executescript(SCHEMA)


def rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


def jload(v, default=None):
    if not v:
        return default
    try:
        return json.loads(v)
    except (TypeError, json.JSONDecodeError):
        return default
