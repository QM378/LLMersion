"""Read-only signals from the reader, if a reader exists.

Two ideas live here, both optional -- the curator runs fine without a reader:

* Saved vocabulary as a ranking signal: candidates are scored by how densely
  the learner's saved words re-occur in them (with per-word saturation), so a
  night's pick doubles as an engineered re-encounter with exactly the words the
  learner is struggling with.
* Reading progress as implicit feedback: the reader keys progress by document
  content hash, so the curator can ask -- with no new instrumentation -- whether
  a past pick was actually opened and how far it went, and convert that into a
  soft rating. Explicit ratings from `curator.feedback` always override.

Access is strictly read-only; the curator never writes the reader's database.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
from pathlib import Path

from . import config

_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]+")


def _reader_db() -> Path | None:
    p = config.data_dir().parent / "reader.db"
    return p if p.exists() else None


def saved_words(limit: int = 400) -> set[str]:
    db = _reader_db()
    if not db:
        return set()
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        rows = conn.execute(
            "SELECT word FROM vocab ORDER BY last DESC LIMIT ?", (limit,)).fetchall()
        conn.close()
        return {r[0].lower() for r in rows}
    except Exception:
        return set()


def reencounter_score(text: str, words: set[str]) -> float:
    """Density of saved words in `text`, each word counted at most 3 times
    (saturation), per 100 tokens. 0.0 when there is no vocabulary to match."""
    if not words:
        return 0.0
    toks = [t.lower() for t in _WORD.findall(text)]
    if not toks:
        return 0.0
    hits: dict[str, int] = {}
    for t in toks:
        if t in words and hits.get(t, 0) < 3:
            hits[t] = hits.get(t, 0) + 1
    return 100.0 * sum(hits.values()) / len(toks)


def content_hash(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()[:16]


def progress_for(doc_hash: str) -> tuple[int, int] | None:
    """(paragraph, sentence) the reader last saved for this document, or None."""
    db = _reader_db()
    if not db:
        return None
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        row = conn.execute("SELECT para, sent FROM progress WHERE doc_id=?",
                           (doc_hash,)).fetchone()
        conn.close()
        return (row[0], row[1]) if row else None
    except Exception:
        return None
