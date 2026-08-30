"""Curator state: what has been prepared, and how the learner rated it.

A single SQLite file. This is the agent's memory: `items` records every
document ever prepared (so nothing repeats), ratings attach to items, and
`discovered` holds related topics harvested from well-rated material -- the
pool the exploration step draws from.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from . import config

_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS items(
    id TEXT PRIMARY KEY,          -- source-native id (arxiv id, wiki pageid)
    source TEXT, topic TEXT, title TEXT, path TEXT,
    created REAL, rating INTEGER,  -- NULL until rated
    hash TEXT, implicit INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS discovered(
    topic TEXT PRIMARY KEY, via TEXT, added REAL
);
"""


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        path = config.data_dir() / "curator.db"
        _conn = sqlite3.connect(path)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(SCHEMA)
    return _conn


def seen(item_id: str) -> bool:
    return conn().execute("SELECT 1 FROM items WHERE id=?", (item_id,)).fetchone() is not None


def add_item(item_id: str, source: str, topic: str, title: str, path: Path,
             doc_hash: str = "") -> None:
    conn().execute(
        "INSERT OR IGNORE INTO items(id,source,topic,title,path,created,hash)"
        " VALUES(?,?,?,?,?,?,?)",
        (item_id, source, topic, title, str(path), time.time(), doc_hash))
    conn().commit()


def rate(item_id: str, rating: int, implicit: bool = False) -> None:
    """Explicit ratings always win: an implicit one never overwrites explicit."""
    if implicit:
        conn().execute(
            "UPDATE items SET rating=?, implicit=1 WHERE id=? AND "
            "(rating IS NULL OR implicit=1)", (max(0, min(5, rating)), item_id))
    else:
        conn().execute("UPDATE items SET rating=?, implicit=0 WHERE id=?",
                       (max(0, min(5, rating)), item_id))
    conn().commit()


def pending_implicit(min_age_s: float = 86400) -> list:
    """Items with no explicit rating, delivered at least a day ago."""
    return conn().execute(
        "SELECT * FROM items WHERE (rating IS NULL OR implicit=1) "
        "AND created < ? AND hash != ''",
        (time.time() - min_age_s,)).fetchall()


def unrated(limit: int = 20) -> list[sqlite3.Row]:
    return conn().execute(
        "SELECT * FROM items WHERE rating IS NULL ORDER BY created DESC LIMIT ?",
        (limit,)).fetchall()


def topic_stats() -> dict[str, tuple[float, int]]:
    """topic -> (mean rating, n rated)."""
    rows = conn().execute(
        "SELECT topic, AVG(rating) m, COUNT(rating) n FROM items "
        "WHERE rating IS NOT NULL GROUP BY topic").fetchall()
    return {r["topic"]: (r["m"], r["n"]) for r in rows}


def add_discovered(topic: str, via: str) -> None:
    conn().execute("INSERT OR IGNORE INTO discovered(topic,via,added) VALUES(?,?,?)",
                   (topic.strip(), via, time.time()))
    conn().commit()


def discovered_topics() -> list[str]:
    return [r["topic"] for r in conn().execute(
        "SELECT topic FROM discovered ORDER BY added DESC LIMIT 50")]
