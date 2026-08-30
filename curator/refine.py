"""Rewrite raw text into read-aloud-ready prose with a local LLM.

The prompt matches the reader's `tools/distill.py` on purpose (kept as a copy,
not an import, so the curator has zero dependencies on the reader's code). If
Ollama is not running, material is still produced -- rule-based cleanup only --
because a slightly rough document tomorrow morning beats no document.
"""
from __future__ import annotations

import re

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
"""

SIMPLIFY = """- Prefer shorter sentences and common words where the technical \
meaning permits; this is for a language learner.
"""

_REF = re.compile(r"\[\d+(?:,\s*\d+)*\]")
_WS = re.compile(r"[ \t]+")


def cleanup(text: str) -> str:
    """The no-LLM fallback: strip citation markers and normalise whitespace."""
    out = _WS.sub(" ", _REF.sub("", text))
    return re.sub(r"\s+([.,;:!?])", r"\1", out).strip()


def ollama_ok(url: str) -> bool:
    try:
        import requests
        requests.get(f"{url}/api/tags", timeout=3).raise_for_status()
        return True
    except Exception:
        return False


def rewrite(text: str, model: str, url: str, simplify: bool = False,
            timeout: int = 180) -> str:
    import requests
    prompt = PROMPT + (SIMPLIFY if simplify else "") + "\nParagraph:\n" + text
    r = requests.post(f"{url}/api/chat",
                      json={"model": model, "stream": False,
                            "options": {"temperature": 0.2, "num_ctx": 4096},
                            "messages": [{"role": "user", "content": prompt}]},
                      timeout=timeout)
    r.raise_for_status()
    out = r.json().get("message", {}).get("content", "").strip()
    if "</think>" in out:
        out = out.split("</think>")[-1].strip()
    return out or cleanup(text)
