"""Conversation history, in its own database file.

Deliberately not a new table inside `reader.db`: the module is meant to be
droppable and removable without migrating anyone's reading data, and a second
process writing to the reader's file is a needless risk. Reads of vocabulary
and documents still go through the reader's own layer.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time

from . import config

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS session (
    id      TEXT PRIMARY KEY,
    doc_id  TEXT,
    title   TEXT,
    para    INTEGER,
    started REAL,
    ended   REAL,
    mode    TEXT,
    topic   TEXT
);
CREATE TABLE IF NOT EXISTS turn (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    session TEXT,
    role    TEXT,          -- tutor | learner
    text    TEXT,
    used    TEXT,          -- JSON list of target words present in this turn
    score   INTEGER,       -- pronunciation score, learner turns only
    fixed   TEXT,          -- corrected sentence, learner turns only
    why     TEXT,          -- the rule behind the correction, in Chinese
    secs    REAL,
    ts      REAL
);
CREATE INDEX IF NOT EXISTS turn_session ON turn(session);
"""

MIGRATIONS = {
    "session": {"mode": "TEXT", "topic": "TEXT"},
    "turn": {"fixed": "TEXT", "why": "TEXT"},
}


def conn() -> sqlite3.Connection:
    c = getattr(_local, "conn", None)
    if c is None:
        c = sqlite3.connect(config.DB_PATH, timeout=30, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(SCHEMA)
        for table, cols in MIGRATIONS.items():
            have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
            for name, decl in cols.items():
                if name not in have:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
        c.commit()
        _local.conn = c
    return c


def new_session(sid: str, mode: str, doc_id: str, title: str, para: int,
                topic: str = "") -> None:
    conn().execute(
        "INSERT OR REPLACE INTO session (id,doc_id,title,para,started,ended,mode,topic)"
        " VALUES (?,?,?,?,?,NULL,?,?)",
        (sid, doc_id, title, para, time.time(), mode, topic))
    conn().commit()


def add_turn(session: str, role: str, text: str, used: list[str] | None = None,
             score: int | None = None, fixed: str = "", why: str = "",
             secs: float = 0.0) -> None:
    conn().execute(
        "INSERT INTO turn (session,role,text,used,score,fixed,why,secs,ts)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (session, role, text, json.dumps(used or []), score, fixed, why,
         secs, time.time()))
    conn().commit()


def history(session: str, limit: int = 60) -> list[dict]:
    rows = conn().execute(
        "SELECT role,text,used,score,fixed,why,ts FROM turn WHERE session=?"
        " ORDER BY id LIMIT ?", (session, limit)).fetchall()
    return [{"role": r["role"], "text": r["text"],
             "used": json.loads(r["used"] or "[]"), "score": r["score"],
             "fixed": r["fixed"] or "", "why": r["why"] or "", "ts": r["ts"]}
            for r in rows]


def sessions(limit: int = 30) -> list[dict]:
    rows = conn().execute(
        "SELECT s.*, (SELECT COUNT(*) FROM turn t WHERE t.session=s.id) n"
        " FROM session s ORDER BY started DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def stats(session: str) -> dict:
    """What the learner actually produced — the numbers worth watching."""
    rows = conn().execute(
        "SELECT used,score,fixed FROM turn WHERE session=? AND role='learner'",
        (session,)).fetchall()
    words: set[str] = set()
    scores, fixes = [], 0
    for r in rows:
        words.update(json.loads(r["used"] or "[]"))
        if r["score"] is not None:
            scores.append(r["score"])
        if r["fixed"]:
            fixes += 1
    return {"turns": len(rows), "words": sorted(words), "fixes": fixes,
            "score_avg": round(sum(scores) / len(scores)) if scores else None}


def word_history(days: int = 90) -> dict[str, int]:
    """How many times each target word has been spoken, across all sessions."""
    since = time.time() - days * 86400
    out: dict[str, int] = {}
    for r in conn().execute(
            "SELECT used FROM turn WHERE role='learner' AND ts>?", (since,)):
        for w in json.loads(r["used"] or "[]"):
            out[w] = out.get(w, 0) + 1
    return out
