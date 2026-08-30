"""Rate prepared material: the learning half of the agent loop.

    python -m curator.feedback           # rate everything unrated, interactively
    python -m curator.feedback --list    # show recent items and their ratings

Ratings are 0-5 (0 = useless to me, 5 = exactly what I want more of). They do
two things: shift the topic weights for future nights, and -- at 4 or above --
promote the item's related topics into the exploration pool.
"""
from __future__ import annotations

import argparse

from . import store


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list", action="store_true", help="show recent items only")
    args = ap.parse_args()

    if args.list:
        rows = store.conn().execute(
            "SELECT * FROM items ORDER BY created DESC LIMIT 20").fetchall()
        for r in rows:
            mark = "·" if r["rating"] is None else str(r["rating"])
            print(f"  [{mark}] {r['topic']:<24} {r['title'][:56]}")
        return 0

    rows = store.unrated()
    if not rows:
        print("nothing unrated — run `python -m curator.run` tonight")
        return 0
    print("rate 0-5, Enter to skip, q to quit\n")
    for r in rows:
        try:
            ans = input(f"  {r['title'][:64]}  ({r['topic']})  > ").strip()
        except EOFError:
            break
        if ans.lower() == "q":
            break
        if ans.isdigit():
            store.rate(r["id"], int(ans))
    stats = store.topic_stats()
    if stats:
        print("\ncurrent topic standing:")
        for t, (m, n) in sorted(stats.items(), key=lambda kv: -kv[1][0]):
            print(f"  {t:<28} {m:.1f}  ({n} rated)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
