"""Vocabulary-gap profiling: where do the learner's unknown words concentrate?

Nightly, the curator hands the learner's recently saved words (with the
sentences they came from) to the local LLM and asks for coarse domain labels.
The resulting profile does two things: it is printed for the learner, and its
top domains join the exploration pool, so material supply drifts toward the
areas where lookups actually cluster. Read-only on the reader's store, as
always; without Ollama the step is skipped and nothing else changes.
"""
from __future__ import annotations

import json
import re
import sqlite3

from . import config, store

PROMPT = """A language learner saved these English words while reading (some
with the sentence they came from). Group them into 3 to 6 coarse technical or
topical domains. Reply with ONLY a JSON object mapping each domain name (2-4
words, English) to the list of words that belong to it. No other text.

Words:
"""


def recent_vocab(limit: int = 150) -> list[tuple[str, str]]:
    db = config.data_dir().parent / "reader.db"
    if not db.exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        rows = conn.execute(
            "SELECT word, COALESCE(context,'') FROM vocab "
            "WHERE known=0 ORDER BY last DESC LIMIT ?", (limit,)).fetchall()
        conn.close()
        return [(w, c) for w, c in rows]
    except Exception:
        return []


def _parse(raw: str) -> dict[str, list[str]]:
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
    except Exception:
        return {}
    return {str(k): [str(w) for w in v] for k, v in data.items()
            if isinstance(v, list) and v}


def build(llm) -> dict[str, int]:
    """llm: callable(prompt) -> str. Returns {domain: word count}, largest first."""
    vocab = recent_vocab()
    if len(vocab) < 10:
        return {}
    lines = [f"{w} — {c[:90]}" if c else w for w, c in vocab]
    grouped = _parse(llm(PROMPT + "\n".join(lines)))
    prof = {d: len(ws) for d, ws in grouped.items()}
    return dict(sorted(prof.items(), key=lambda kv: -kv[1]))


def apply(profile: dict[str, int], top_n: int = 3) -> None:
    for domain in list(profile)[:top_n]:
        store.add_discovered(domain, via="vocabulary profile")
