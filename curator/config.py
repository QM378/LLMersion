"""Curator configuration and paths.

The curator is deliberately decoupled from the reader: it shares no code with
the server, and the only contract between them is the filesystem -- the curator
writes ordinary Markdown files into a library folder, and the reader opens them
like any other document. Either program is fully functional without the other.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

DEFAULTS = {
    # what the learner wants to read about; ratings reweight these over time
    "topics": ["machine learning", "distributed systems", "linguistics"],
    # documents to prepare per night
    "per_night": 2,
    # mix of sources, as a weight; wikipedia is fast, arxiv is heavier
    "sources": {"wikipedia": 1.0, "arxiv": 1.0},
    # local LLM used to rewrite text for reading aloud ("" disables the rewrite
    # and keeps rule-based cleanup only)
    "model": "gemma3:4b",
    "ollama_url": "http://127.0.0.1:11434",
    # 0 = keep the original register; 1 = allow mild simplification for learners
    "simplify": 0,
    # exploration rate: how often a night includes a topic *related* to what was
    # rated well, instead of a configured topic
    "epsilon": 0.25,
    # cap on arxiv PDF pages, to keep a night's work bounded
    "max_pdf_pages": 30,
}


def data_dir() -> Path:
    if os.environ.get("PR_DATA"):
        base = Path(os.environ["PR_DATA"])
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "ReadingDesk"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "ReadingDesk"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "ReadingDesk"
    return base / "curator"


def library_dir() -> Path:
    return data_dir().parent / "library"


def load() -> dict:
    """Read config.json from the data dir, creating it with defaults on first run
    so the learner has a file to edit rather than code to read."""
    d = data_dir()
    d.mkdir(parents=True, exist_ok=True)
    library_dir().mkdir(parents=True, exist_ok=True)
    path = d / "config.json"
    if not path.exists():
        path.write_text(json.dumps(DEFAULTS, indent=2), encoding="utf-8")
        return dict(DEFAULTS)
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(path.read_text(encoding="utf-8")))
    except Exception as exc:  # noqa: BLE001
        print(f"[curator] config.json unreadable ({exc}); using defaults")
    return cfg
