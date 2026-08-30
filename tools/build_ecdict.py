#!/usr/bin/env python3
"""Compile ECDICT's stardict.csv into a fast local SQLite dictionary.

Get the data from https://github.com/skywind3000/ECDICT (stardict.csv, ~3.4M words),
then:

    python tools/build_ecdict.py /path/to/stardict.csv data/ecdict.db

The `exchange` column is mined to build a form -> base-word table, so looking up
"studies" or "ran" lands on "study" / "run" without shipping a POS tagger.
"""
from __future__ import annotations

import csv
import sqlite3
import sys
from pathlib import Path

SCHEMA = """
DROP TABLE IF EXISTS entry;
DROP TABLE IF EXISTS lemma;
CREATE TABLE entry (
    word TEXT PRIMARY KEY, phonetic TEXT, definition TEXT,
    translation TEXT, pos TEXT, collins INTEGER, oxford INTEGER,
    tag TEXT, bnc INTEGER, frq INTEGER, exchange TEXT
);
CREATE TABLE lemma (form TEXT PRIMARY KEY, base TEXT);
"""


def _int(v: str | None) -> int:
    try:
        return int(v or 0)
    except ValueError:
        return 0


def main(src: str, dst: str) -> None:
    csv.field_size_limit(10_000_000)
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(dst)
    db.executescript(SCHEMA)
    rows: list[tuple] = []
    lemmas: list[tuple] = []
    n = 0

    def flush() -> None:
        db.executemany("INSERT OR REPLACE INTO entry VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
        db.executemany("INSERT OR IGNORE INTO lemma VALUES (?,?)", lemmas)
        rows.clear()
        lemmas.clear()

    with open(src, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            w = (r.get("word") or "").strip().lower()
            if not w:
                continue
            rows.append((w, r.get("phonetic", ""), r.get("definition", ""),
                         r.get("translation", ""), r.get("pos", ""),
                         _int(r.get("collins")), _int(r.get("oxford")),
                         r.get("tag", ""), _int(r.get("bnc")), _int(r.get("frq")),
                         r.get("exchange", "")))
            for item in (r.get("exchange") or "").split("/"):
                if ":" in item:
                    kind, form = item.split(":", 1)
                    form = form.strip().lower()
                    if form and kind != "0":
                        lemmas.append((form, w))
            n += 1
            if len(rows) >= 20000:
                flush()
                print(f"  {n:,} entries", end="\r", flush=True)
    flush()
    db.commit()
    db.execute("VACUUM")
    db.close()
    print(f"\nbuilt {dst} with {n:,} entries")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(1)
    main(sys.argv[1], sys.argv[2])
