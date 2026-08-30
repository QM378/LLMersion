"""Tiny SQLite persistence layer. One connection per thread, WAL mode."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from typing import Any, Optional

from . import config

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS doc (
    doc_id TEXT PRIMARY KEY,
    title  TEXT,
    pages  INTEGER,
    meta   TEXT,
    paras  TEXT,
    added  REAL
);
CREATE TABLE IF NOT EXISTS audio (
    key    TEXT PRIMARY KEY,     -- sha1(engine|voice|speed|text)
    fname  TEXT,
    engine TEXT,
    added  REAL,
    marks  TEXT,                 -- JSON [[startFrac, endFrac], ...] per sentence
    method TEXT                  -- how the marks were obtained
);
CREATE TABLE IF NOT EXISTS trans (
    key    TEXT PRIMARY KEY,     -- sha1(model|text)
    zh     TEXT,
    added  REAL
);
CREATE TABLE IF NOT EXISTS progress (
    doc_id TEXT PRIMARY KEY,
    para   INTEGER,
    sent   INTEGER,
    ts     REAL
);
CREATE TABLE IF NOT EXISTS vocab (
    word   TEXT PRIMARY KEY,
    zh     TEXT,
    phonetic TEXT,
    context TEXT,
    doc_id TEXT,
    ts     REAL,
    hits   INTEGER DEFAULT 1,
    known  INTEGER DEFAULT 0,
    last   REAL
);
"""

# columns added after the first release; applied to existing databases on open
MIGRATIONS = {
    "vocab": {"hits": "INTEGER DEFAULT 1", "known": "INTEGER DEFAULT 0", "last": "REAL",
              "best": "INTEGER DEFAULT 0", "tries": "INTEGER DEFAULT 0"},
    "audio": {"marks": "TEXT", "method": "TEXT"},
}


def conn() -> sqlite3.Connection:
    c = getattr(_local, "conn", None)
    if c is None:
        c = sqlite3.connect(config.DB_PATH, timeout=30, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.executescript(SCHEMA)
        for table, cols in MIGRATIONS.items():
            have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
            for name, decl in cols.items():
                if name not in have:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
        c.commit()
        _local.conn = c
    return c


def sha1(*parts: str) -> str:
    h = hashlib.sha1()
    for p in parts:
        h.update(p.encode("utf-8", "replace"))
        h.update(b"\x00")
    return h.hexdigest()


# ---------------------------------------------------------------- doc
def put_doc(doc_id: str, title: str, pages: int, meta: dict, paras: list) -> None:
    conn().execute(
        "INSERT OR REPLACE INTO doc VALUES (?,?,?,?,?,?)",
        (doc_id, title, pages, json.dumps(meta, ensure_ascii=False),
         json.dumps(paras, ensure_ascii=False), time.time()),
    )
    conn().commit()


def get_doc(doc_id: str) -> Optional[dict]:
    r = conn().execute("SELECT * FROM doc WHERE doc_id=?", (doc_id,)).fetchone()
    if not r:
        return None
    return {
        "doc_id": r["doc_id"], "title": r["title"], "pages": r["pages"],
        "meta": json.loads(r["meta"]), "paragraphs": json.loads(r["paras"]),
    }


def list_docs(limit: int = 50) -> list[dict]:
    rows = conn().execute(
        "SELECT doc_id,title,pages,added FROM doc ORDER BY added DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- audio
def get_audio(key: str) -> Optional[dict]:
    r = conn().execute("SELECT * FROM audio WHERE key=?", (key,)).fetchone()
    if not r:
        return None
    if not (config.AUDIO_DIR / r["fname"]).exists():
        conn().execute("DELETE FROM audio WHERE key=?", (key,))
        conn().commit()
        return None
    return {"fname": r["fname"],
            "marks": json.loads(r["marks"]) if r["marks"] else None,
            "method": r["method"] or ""}


def put_audio(key: str, fname: str, engine: str,
              marks: list | None = None, method: str = "") -> None:
    conn().execute(
        "INSERT OR REPLACE INTO audio (key,fname,engine,added,marks,method) VALUES (?,?,?,?,?,?)",
        (key, fname, engine, time.time(),
         json.dumps(marks) if marks else None, method))
    conn().commit()


# ---------------------------------------------------------------- translation
def get_trans(key: str) -> Optional[str]:
    r = conn().execute("SELECT zh FROM trans WHERE key=?", (key,)).fetchone()
    return r["zh"] if r else None


def put_trans(key: str, zh: str) -> None:
    conn().execute("INSERT OR REPLACE INTO trans VALUES (?,?,?)", (key, zh, time.time()))
    conn().commit()


# ---------------------------------------------------------------- progress / vocab
def set_progress(doc_id: str, para: int, sent: int) -> None:
    conn().execute("INSERT OR REPLACE INTO progress VALUES (?,?,?,?)",
                   (doc_id, para, sent, time.time()))
    conn().commit()


def get_progress(doc_id: str) -> dict[str, Any]:
    r = conn().execute("SELECT para,sent FROM progress WHERE doc_id=?", (doc_id,)).fetchone()
    return {"para": r["para"], "sent": r["sent"]} if r else {"para": 0, "sent": 0}


def add_vocab(word: str, zh: str, phonetic: str, context: str, doc_id: str) -> None:
    """Insert, or bump the hit count if the word is already on the list."""
    now = time.time()
    conn().execute(
        """
        INSERT INTO vocab (word, zh, phonetic, context, doc_id, ts, hits, known, last)
        VALUES (?,?,?,?,?,?,1,0,?)
        ON CONFLICT(word) DO UPDATE SET
            hits = hits + 1,
            last = excluded.last,
            zh       = CASE WHEN vocab.zh IS NULL OR vocab.zh = ''
                            THEN excluded.zh ELSE vocab.zh END,
            phonetic = CASE WHEN vocab.phonetic IS NULL OR vocab.phonetic = ''
                            THEN excluded.phonetic ELSE vocab.phonetic END,
            context  = CASE WHEN vocab.context IS NULL OR vocab.context = ''
                            THEN excluded.context ELSE vocab.context END
        """,
        (word.strip().lower(), zh, phonetic, context, doc_id, now, now),
    )
    conn().commit()


def del_vocab(word: str) -> None:
    conn().execute("DELETE FROM vocab WHERE word=?", (word.strip().lower(),))
    conn().commit()


def set_known(word: str, known: int) -> None:
    conn().execute("UPDATE vocab SET known=?, last=? WHERE word=?",
                   (int(known), time.time(), word.strip().lower()))
    conn().commit()


def record_score(word: str, score: int) -> None:
    conn().execute(
        "UPDATE vocab SET tries = COALESCE(tries,0) + 1,"
        " best = MAX(COALESCE(best,0), ?), last = ? WHERE word = ?",
        (int(score), time.time(), word.strip().lower()))
    conn().commit()


def list_vocab(limit: int = 5000) -> list[dict]:
    rows = conn().execute(
        "SELECT * FROM vocab ORDER BY ts DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def merge_vocab(base_of) -> dict:
    """Fold inflected forms into their base word.

    `base_of(word) -> str` comes from the dictionary's lemma table. Rows that map
    to the same base are combined: earliest date wins, hits are summed, `known`
    survives if any form was marked known, and the first non-empty gloss,
    phonetic and context are kept.
    """
    rows = [dict(r) for r in conn().execute("SELECT * FROM vocab")]
    groups: dict[str, list[dict]] = {}
    for r in rows:
        base = (base_of(r["word"]) or r["word"]).strip().lower()
        groups.setdefault(base, []).append(r)

    removed = 0
    changed = 0
    c = conn()
    for base, items in groups.items():
        if len(items) == 1 and items[0]["word"] == base:
            continue
        items.sort(key=lambda r: (r["word"] != base, r["ts"] or 0))
        merged = {
            "word": base,
            "zh": next((r["zh"] for r in items if r["zh"]), ""),
            "phonetic": next((r["phonetic"] for r in items if r["phonetic"]), ""),
            "context": next((r["context"] for r in items if r["context"]), ""),
            "doc_id": next((r["doc_id"] for r in items if r["doc_id"]), ""),
            "ts": min((r["ts"] or time.time()) for r in items),
            "hits": sum(r["hits"] or 1 for r in items),
            "known": max(r["known"] or 0 for r in items),
            "last": max((r["last"] or r["ts"] or 0) for r in items),
        }
        for r in items:
            c.execute("DELETE FROM vocab WHERE word=?", (r["word"],))
        removed += len(items) - 1
        changed += 1
        c.execute(
            "INSERT OR REPLACE INTO vocab (word,zh,phonetic,context,doc_id,ts,hits,known,last)"
            " VALUES (:word,:zh,:phonetic,:context,:doc_id,:ts,:hits,:known,:last)",
            merged,
        )
    c.commit()
    return {"groups": changed, "removed": removed,
            "total": c.execute("SELECT COUNT(*) n FROM vocab").fetchone()["n"]}
