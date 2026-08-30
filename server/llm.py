"""Local LLM helper for learning features (writing feedback, simplification).

One narrow function over the Ollama chat API. Every use in the reader is a
place where the model's output is inspectable by the learner --- a correction
they can compare against their draft, a paraphrase they can compare against
the original --- in keeping with the system's rule of never using a generative
model as an unverifiable oracle.
"""
from __future__ import annotations

import os

import requests

from . import config

MODEL = os.environ.get("PR_LLM_MODEL", "gemma3:4b")


def available() -> bool:
    try:
        requests.get(f"{config.OLLAMA_URL}/api/tags", timeout=2).raise_for_status()
        return True
    except Exception:
        return False


def chat(prompt: str, temperature: float = 0.3, timeout: int = 180) -> str:
    r = requests.post(f"{config.OLLAMA_URL}/api/chat",
                      json={"model": MODEL, "stream": False,
                            "options": {"temperature": temperature, "num_ctx": 4096},
                            "messages": [{"role": "user", "content": prompt}]},
                      timeout=timeout)
    r.raise_for_status()
    out = r.json().get("message", {}).get("content", "").strip()
    if "</think>" in out:
        out = out.split("</think>")[-1].strip()
    return out


WRITE_PROMPT = """You are an English writing tutor for a second-language
learner. They studied a text and wrote the passage below (a summary, retelling,
or response). Give feedback in this exact structure, in English, concise:

**Corrected version** — their passage with errors fixed, changes in **bold**.
**Notes** — the 2-4 most instructive issues, one line each: what was wrong and
the rule or pattern behind it. Skip trivia.
**Vocabulary** — the learner is working on these words: {vocab}. Say which
they used well, and pick ONE more that would fit naturally in this passage,
showing the sentence with it in place. If none fit, say so.

Do not rewrite their ideas, praise emptily, or add commentary outside the
three sections.

Their passage:
{text}
"""

SIMPLIFY_PROMPT = """Rewrite the following English paragraph for a
second-language learner: shorter sentences, common words, technical terms kept
but each explained in a few words in parentheses on first use. Preserve every
claim. Output only the rewritten paragraph.

Paragraph:
{text}
"""
