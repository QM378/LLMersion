"""Word lookup.

Primary source is ECDICT (github.com/skywind3000/ECDICT, CC-BY / MIT-ish, 3.4M
entries with phonetics, definitions and inflection tables) compiled into a local
SQLite file by ``tools/build_ecdict.py``. Everything is offline and O(1).

If the dictionary is missing we degrade to the translation backend, which still
gives a usable meaning for the selected word or phrase.
"""
from __future__ import annotations

import re
import sqlite3
import threading
from typing import Optional

from . import config

_local = threading.local()
_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]*")


def _conn() -> Optional[sqlite3.Connection]:
    if not config.DICT_DB.exists():
        return None
    c = getattr(_local, "dict", None)
    if c is None:
        c = sqlite3.connect(config.DICT_DB, check_same_thread=False)
        c.row_factory = sqlite3.Row
        _local.dict = c
    return c


def available() -> bool:
    return _conn() is not None


def _row(c: sqlite3.Connection, w: str):
    return c.execute("SELECT * FROM entry WHERE word=?", (w,)).fetchone()


def _naive_lemmas(w: str) -> list[str]:
    out = []
    for suf, reps in (("ies", ["y"]), ("es", ["", "e"]), ("s", [""]),
                      ("ied", ["y"]), ("ed", ["", "e"]), ("ing", ["", "e"]),
                      ("est", ["", "e"]), ("er", ["", "e"]), ("ly", [""])):
        if w.endswith(suf) and len(w) > len(suf) + 2:
            stem = w[: -len(suf)]
            out.extend(stem + r for r in reps)
            if len(stem) > 2 and stem[-1] == stem[-2]:
                out.append(stem[:-1])
    return out


def base_form(word: str) -> str:
    """Return the dictionary head word for an inflected form ('studies' -> 'study')."""
    w = word.strip().lower()
    if not w or " " in w:
        return w
    c = _conn()
    if c is None:
        for cand in _naive_lemmas(w):
            if cand and len(cand) > 2:
                return cand
        return w
    if _row(c, w) is not None:
        lem = c.execute("SELECT base FROM lemma WHERE form=?", (w,)).fetchone()
        # a word can be both a valid entry and an inflection ("studies"); prefer
        # the base only when the base is itself a known entry
        if lem and _row(c, lem["base"]) is not None and lem["base"] != w:
            return lem["base"]
        return w
    lem = c.execute("SELECT base FROM lemma WHERE form=?", (w,)).fetchone()
    if lem:
        return lem["base"]
    for cand in _naive_lemmas(w):
        if _row(c, cand) is not None:
            return cand
    return w


def lookup(query: str) -> dict:
    q = query.strip()
    if not q:
        return {}
    words = _WORD.findall(q)
    is_phrase = len(words) > 1
    head = q.lower() if not is_phrase else q

    result = {"query": q, "word": q, "phonetic": "", "translation": "",
              "definition": "", "tag": "", "source": "none", "lemma_of": ""}

    c = _conn()
    if c is not None and not is_phrase:
        w = head
        r = _row(c, w)
        if r is None:
            lem = c.execute("SELECT base FROM lemma WHERE form=?", (w,)).fetchone()
            if lem:
                r = _row(c, lem["base"])
                if r:
                    result["lemma_of"] = lem["base"]
        if r is None:
            for cand in _naive_lemmas(w):
                r = _row(c, cand)
                if r:
                    result["lemma_of"] = cand
                    break
        if r is not None:
            result.update({
                "word": r["word"],
                "phonetic": r["phonetic"] or "",
                "translation": (r["translation"] or "").replace("\\n", "\n"),
                "definition": (r["definition"] or "").replace("\\n", "\n"),
                "tag": r["tag"] or "",
                "source": "ecdict",
            })
            return result

    # fall back to MT for phrases / unknown words
    from . import translate as mt
    zh = mt.translate([q])[0]
    result["translation"] = zh
    result["source"] = "mt" if zh else "none"
    return result
