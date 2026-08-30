"""The nightly loop: pick topics, fetch, refine, write, remember.

Run it by hand:
    python -m curator.run              # one night's work, then exit
    python -m curator.run --demo       # offline: exercises the whole pipeline
                                       # with built-in text, no network, no LLM
    python -m curator.run --no-llm     # fetch + rule cleanup only

Schedule it (see curator/README.md) and it becomes what it is named for: by
morning, the library folder holds one or two fresh documents, cleaned for
reading aloud, on topics weighted by how the learner rated previous nights.

The agent loop, spelled out: PERCEIVE (query Wikipedia / arXiv), DECIDE
(epsilon-greedy over topic ratings), ACT (fetch, rewrite for read-aloud,
write Markdown), LEARN (ratings from `python -m curator.feedback` shift the
next night's topic weights, and well-rated items contribute related topics to
the exploration pool). No engagement metrics, no telemetry: the only signal is
the rating the learner chooses to give.
"""
from __future__ import annotations

import argparse
import datetime as dt
import time
import random
import re
import time

from . import config, profile, refine, select, signals, store

DEMO_DOC = {
    "id": "demo:gradient-descent",
    "title": "Gradient Descent",
    "url": "https://example.org/demo",
    "paragraphs": [
        {"kind": "heading", "text": "Definition"},
        {"kind": "body", "text": "Gradient descent minimizes f(x) by iterating "
         "x_{t+1} = x_t - a * grad f(x_t), where a is the learning rate [1]."},
        {"kind": "body", "text": "Convergence for convex f is O(1/t) (see Fig. 2), "
         "and momentum variants improve the constant [2, 3]."},
    ],
}


def slug(title: str, n: int = 48) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-").lower()
    return s[:n] or "untitled"


def write_markdown(doc: dict, topic: str, source: str, refined: list[str]) -> str:
    """Emit the library file. The header comment is the provenance record --
    source URL, license note, and the one-line instruction for rating."""
    date = dt.date.today().isoformat()
    lic = ("Text derived from Wikipedia (CC BY-SA 4.0); attribution and "
           "share-alike apply." if source == "wikipedia" else
           "Derived from an arXiv preprint; see the source for its license.")
    lines = [
        f"<!-- LLMersion-1 curator | {date} | topic: {topic} | source: {doc['url']}",
        f"     {lic}",
        f"     Rate this material:  python -m curator.feedback  (id: {doc['id']}) -->",
        "",
        f"# {doc['title']}",
        "",
    ]
    i = 0
    for p in doc["paragraphs"]:
        if p["kind"] == "heading":
            lines += [f"## {p['text']}", ""]
        else:
            lines += [refined[i], ""]
            i += 1
    path = config.library_dir() / f"{date}-{slug(doc['title'])}.md"
    data = "\n".join(lines).encode("utf-8")
    path.write_bytes(data)
    return str(path), signals.content_hash(data)


def prepare(doc: dict, topic: str, source: str, cfg: dict, use_llm: bool) -> str:
    bodies = [p["text"] for p in doc["paragraphs"] if p["kind"] == "body"]
    refined = []
    for k, text in enumerate(bodies, 1):
        if use_llm:
            try:
                refined.append(refine.rewrite(text, cfg["model"], cfg["ollama_url"],
                                              simplify=bool(cfg.get("simplify"))))
            except Exception as exc:  # noqa: BLE001
                print(f"  rewrite failed ({exc.__class__.__name__}); keeping cleanup")
                refined.append(refine.cleanup(text))
        else:
            refined.append(refine.cleanup(text))
        print(f"\r  {doc['title'][:44]}: {k}/{len(bodies)}", end="", flush=True)
    print()
    path, doc_hash = write_markdown(doc, topic, source, refined)
    store.add_item(doc["id"], source, topic, doc["title"], path, doc_hash)
    return path


def one_night(cfg: dict, use_llm: bool, rng: random.Random) -> list[str]:
    from .sources import arxiv_source, wikipedia_source
    topics = select.pick(cfg["topics"], cfg["per_night"], cfg["epsilon"], rng)
    print(f"tonight's topics: {topics}")
    written: list[str] = []
    weights = cfg.get("sources", {"wikipedia": 1.0, "arxiv": 1.0})
    for topic in topics:
        source = rng.choices(list(weights), weights=list(weights.values()))[0]
        try:
            vocab = signals.saved_words()
            if source == "wikipedia":
                # fetch a few candidates and keep the one that re-encounters the
                # learner's saved vocabulary most densely -- tonight's reading
                # doubles as spaced repetition of exactly the words in trouble
                docs = []
                for cand in wikipedia_source.search(topic):
                    if store.seen(cand["id"]) or len(docs) >= 3:
                        continue
                    d = wikipedia_source.fetch(cand["title"])
                    if len(d["paragraphs"]) >= 3:
                        docs.append(d)
                if docs:
                    full = lambda d: " ".join(p["text"] for p in d["paragraphs"])
                    doc = max(docs, key=lambda d: signals.reencounter_score(full(d), vocab))
                    written.append(prepare(doc, topic, source, cfg, use_llm))
                    for rel in wikipedia_source.related(doc["title"])[:4]:
                        store.add_discovered(rel, via=doc["title"])
            else:
                entries = [e for e in arxiv_source.search(topic)
                           if not store.seen(e["id"])]
                if entries:
                    entry = max(entries, key=lambda e:
                                signals.reencounter_score(e["summary"], vocab))
                    doc = arxiv_source.fetch(entry, cfg.get("max_pdf_pages", 30))
                    written.append(prepare(doc, topic, source, cfg, use_llm))
            time.sleep(1)
        except Exception as exc:  # noqa: BLE001 -- one bad source must not kill the night
            print(f"  {source}/{topic} failed: {exc.__class__.__name__}: {exc}")
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo", action="store_true",
                    help="offline run with built-in text; no network, no LLM")
    ap.add_argument("--no-llm", action="store_true", help="skip the Ollama rewrite")
    ap.add_argument("--seed", type=int, default=None, help="deterministic topic picks")
    args = ap.parse_args()

    cfg = config.load()
    rng = random.Random(args.seed)
    print(f"library: {config.library_dir()}")

    # implicit feedback: did the learner actually open past picks? The reader
    # keys progress by content hash, so this costs no new instrumentation.
    for row in store.pending_implicit():
        prog = signals.progress_for(row["hash"])
        if prog is not None:
            store.rate(row["id"], 4, implicit=True)      # opened and read
        elif time.time() - row["created"] > 3 * 86400:
            store.rate(row["id"], 2, implicit=True)      # sat unopened 3 days

    if args.demo:
        path = prepare(dict(DEMO_DOC), topic="demo", source="wikipedia",
                       cfg=cfg, use_llm=False)
        print(f"wrote {path}")
        return 0

    use_llm = (not args.no_llm) and bool(cfg.get("model")) \
        and refine.ollama_ok(cfg["ollama_url"])
    if not use_llm:
        print("LLM rewrite off (no Ollama or --no-llm); rule cleanup only")

    if use_llm:
        def _ollama(prompt: str) -> str:
            import requests
            r = requests.post(f"{cfg['ollama_url']}/api/chat",
                              json={"model": cfg["model"], "stream": False,
                                    "options": {"temperature": 0.1},
                                    "messages": [{"role": "user", "content": prompt}]},
                              timeout=180)
            r.raise_for_status()
            out = r.json().get("message", {}).get("content", "")
            return out.split("</think>")[-1] if "</think>" in out else out
        prof = profile.build(_ollama)
        if prof:
            head = ", ".join(f"{d} ({n})" for d, n in list(prof.items())[:4])
            print(f"vocabulary gaps concentrate in: {head}")
            profile.apply(prof)

    written = one_night(cfg, use_llm, rng)
    if written:
        print("prepared:")
        for w in written:
            print(f"  {w}")
        print("open them in LLMersion-1; rate them with: python -m curator.feedback")
    else:
        print("nothing new tonight (all candidates seen, or sources unreachable)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
