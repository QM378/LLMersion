#!/usr/bin/env python3
"""Distill a document into clean, read-aloud-ready Markdown with a local LLM.

Heuristic extraction is good; it is not perfect. This tool trades a few minutes
of one-time LLM work for input that is clean *by construction*: every paragraph
rewritten as spoken-style prose, mathematical notation verbalized
("x_i^2" -> "x sub i squared"), citation markers dropped, and unreadable
debris excluded. The output is a Markdown file that the reader opens like any
other document -- so the cost is paid once per document, not once per session.

Usage:
    python tools/distill.py paper.pdf paper.md --model gemma3:4b
    python tools/distill.py notes.epub notes.md --model qwen3:8b --workers 6
    python tools/distill.py paper.pdf clean.md --dry-run     # no LLM, cleanup only

Requires a running Ollama (https://ollama.com) unless --dry-run.
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import config, loaders  # noqa: E402

PROMPT = """You are preparing a technical document for text-to-speech reading \
practice by an English learner. Rewrite the paragraph below as clean, natural \
spoken-style English prose, preserving every technical claim and detail.

Rules:
- Verbalize mathematical notation in words: "x_i^2" becomes "x sub i squared", \
"a/b" becomes "a over b", Greek letters by name.
- Remove citation markers such as [3] or (Smith et al., 2020) unless the name \
matters to the sentence.
- Remove figure/table references that point outside the text ("see Fig. 2").
- Expand abbreviations a listener could not parse on first hearing, once.
- Do not summarize, do not shorten, do not add commentary.
- Output ONLY the rewritten paragraph, no preface.

Paragraph:
"""


def rewrite(text: str, model: str, timeout: int = 180) -> str:
    import requests
    r = requests.post(
        f"{config.OLLAMA_URL}/api/chat",
        json={"model": model, "stream": False,
              "options": {"temperature": 0.2, "num_ctx": 4096},
              "messages": [{"role": "user", "content": PROMPT + text}]},
        timeout=timeout)
    r.raise_for_status()
    out = r.json().get("message", {}).get("content", "").strip()
    if "</think>" in out:
        out = out.split("</think>")[-1].strip()
    return out or text


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="pdf / txt / md / html / epub")
    ap.add_argument("output", help="markdown file to write")
    ap.add_argument("--model", default="gemma3:4b", help="Ollama model (default: gemma3:4b)")
    ap.add_argument("--workers", type=int, default=4, help="parallel LLM requests")
    ap.add_argument("--dry-run", action="store_true",
                    help="skip the LLM: just extraction, filtering, and Markdown structure")
    args = ap.parse_args()

    src = Path(args.input)
    if not src.exists():
        print(f"no such file: {src}", file=sys.stderr)
        return 1

    doc = loaders.load(src, src.name)
    paras = doc["paragraphs"]
    speak = [p for p in paras if p["kind"] in ("body", "heading")]
    dropped = len(paras) - len(speak)
    print(f"{doc['title']}: {len(speak)} paragraphs to keep, {dropped} dropped "
          f"(contents lines, formula debris, non-English)")

    if not args.dry_run:
        import requests
        try:
            requests.get(f"{config.OLLAMA_URL}/api/tags", timeout=3).raise_for_status()
        except Exception:
            print("Ollama is not reachable. Install it from https://ollama.com and "
                  f"`ollama pull {args.model}`, or use --dry-run.", file=sys.stderr)
            return 1

    bodies = [p for p in speak if p["kind"] == "body"]
    done = 0

    def work(p: dict) -> None:
        nonlocal done
        p["out"] = rewrite(p["text"], args.model) if not args.dry_run else p["text"]
        done += 1
        print(f"\r  {done}/{len(bodies)}", end="", flush=True)

    if bodies:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
            list(ex.map(work, bodies))
        print()

    lines = [f"# {doc['title']}", ""]
    for p in speak:
        if p["kind"] == "heading":
            lines += [f"## {p['text']}", ""]
        else:
            lines += [p.get("out", p["text"]), ""]

    out = Path(args.output)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out} — open it in LLMersion-1 like any document")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
