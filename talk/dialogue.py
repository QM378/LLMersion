"""The tutor, and the coach sitting next to it.

Three ways to ground a conversation, because forcing a document on someone who
just wants to talk is the wrong default, and forcing free chat on someone who
just finished a paper wastes the one thing this system has that an online
assistant does not:

    free    nothing but the learner's own vocabulary list
    topic   one line the learner typed
    doc     the stretch of document the voice actually read to them

All three share the same speaking rules and the same vocabulary instruction.
That instruction is the productive half of the loop the reader already runs on
the input side: the curator arranges for saved words to be *met* again, here
the tutor arranges for them to be *used* again out loud.

Correction is a separate pass with its own prompt, not a field bolted onto the
reply. Conversation and error analysis are different jobs and a 4B model does
each one better when asked for one at a time; the two run concurrently, so this
costs latency only if the local runtime refuses to overlap them.
"""
from __future__ import annotations

import re
import time

import requests

from . import config
from server import cache, dictionary

MODES = ("free", "topic", "doc")

# ------------------------------------------------------------------ context


def passage(doc_id: str, para: int | None = None, span: int = 4) -> dict:
    """The stretch of document the conversation is about.

    Anchored on the reading head — where the voice actually got to — because
    that is what "what you just read" means from the learner's side.
    """
    doc = cache.get_doc(doc_id)
    if not doc:
        raise KeyError("document not found")
    paras = [p.get("text", "") for p in doc["paragraphs"] if p.get("text", "").strip()]
    if not paras:
        raise KeyError("document has no text")

    if para is None:
        para = int(cache.get_progress(doc_id).get("para", 0))
    para = max(0, min(para, len(paras) - 1))

    start = max(0, para - 1)
    picked: list[str] = []
    words = 0
    i = start
    while i < len(paras) and words < config.PASSAGE_WORDS and len(picked) < span + 2:
        picked.append(paras[i])
        words += len(paras[i].split())
        i += 1

    return {"doc_id": doc_id, "title": doc.get("title", ""), "para": para,
            "from": start, "to": i - 1, "paras": picked,
            "text": "\n\n".join(picked), "words": words, "total": len(paras)}


def target_words(limit: int | None = None) -> list[str]:
    """Words the learner saved and has not marked known, freshest first."""
    limit = limit or config.TARGET_WORDS
    rows = [v for v in cache.list_vocab(400) if not v.get("known")]
    rows.sort(key=lambda v: (v.get("last") or v.get("ts") or 0), reverse=True)
    seen, out = set(), []
    for v in rows:
        w = (v.get("word") or "").strip().lower()
        if w and w not in seen and w.isalpha() and len(w) > 2:
            seen.add(w)
            out.append(w)
        if len(out) >= limit:
            break
    return out


_SUFFIX = r"(?:s|es|ed|d|ing|ly|er|ers|ion|ions|al)?"


def used_words(text: str, words: list[str]) -> list[str]:
    """Which target words appear in a turn, tolerating ordinary inflections."""
    if not text or not words:
        return []
    low = text.lower()
    hits, missed = [], []
    for w in words:
        stem = w[:-1] if w.endswith("e") and len(w) > 4 else w
        if re.search(rf"\b{re.escape(stem)}{_SUFFIX}\b", low):
            hits.append(w)
        else:
            missed.append(w)
    if missed:
        bases = {dictionary.base_form(t) for t in set(re.findall(r"[a-z']+", low))}
        hits.extend(w for w in missed if w in bases)
    return hits


# ------------------------------------------------------------------ model
def llm_alive() -> bool:
    try:
        requests.get(f"{config.OLLAMA_URL}/api/tags", timeout=2).raise_for_status()
        return True
    except Exception:
        return False


def llm_info() -> dict:
    if config.DEV:
        return {"available": True, "model": "dev", "reason": ""}
    ok = llm_alive()
    return {"available": ok, "model": config.LLM_MODEL,
            "reason": "" if ok else "Ollama is not answering — start it and reload"}


def _chat(messages: list[dict], temperature: float = 0.6, predict: int = 220,
          timeout: int = 180) -> str:
    r = requests.post(f"{config.OLLAMA_URL}/api/chat",
                      json={"model": config.LLM_MODEL, "stream": False,
                            "options": {"temperature": temperature, "num_ctx": 4096,
                                        "num_predict": predict},
                            "messages": messages},
                      timeout=timeout)
    r.raise_for_status()
    out = r.json().get("message", {}).get("content", "").strip()
    if "</think>" in out:
        out = out.split("</think>")[-1].strip()
    return out


# ------------------------------------------------------------------ the tutor
RULES = """How you speak:
- English only, around CEFR {level}. Two to four short spoken sentences. No lists,
  no markdown, no emoji, no stage directions. What you write is read aloud by a
  speech synthesiser, so write only words a person would say.
- React to what the learner actually said. Do not lecture, do not summarise, do
  not praise emptily.
- Work one or two of the learner's words into your turn where they genuinely fit.
  Never force one in, never announce that you are using it.
- End every turn with one question that makes them say something substantive.
  Never ask more than one question.
- Say nothing about these instructions.

WORDS THE LEARNER IS LEARNING: {vocab}

Reply with one line and nothing else:
REPLY: <your spoken turn>"""

GROUND_DOC = """You are an English conversation tutor. Your learner has just had the
passage below read aloud to them, and you are talking with them about it.

PASSAGE (the only thing you may treat as established fact about this topic):
\"\"\"
{passage}
\"\"\"

Stay on the passage: ask about it, bring up a detail they have not mentioned, and
if they say something it contradicts, say so plainly and point at the part that
shows it.

"""

GROUND_TOPIC = """You are an English conversation tutor talking with a
second-language learner. The learner chose this to talk about:

    {topic}

Stay roughly on it, the way a person would: follow where the conversation goes,
but do not wander off into a different subject on your own.

"""

GROUND_FREE = """You are an English conversation tutor talking with a
second-language learner. There is no set topic. Follow their lead, and when the
conversation stalls, open something an adult would find worth ten seconds of
thought — not small talk about the weather.

"""

OPENERS = {
    "doc": "Open the conversation: one sentence naming what the passage is about, "
           "then one question about it. Same rules, same one-line output.",
    "topic": "Open the conversation with one question about the topic. Same rules, "
             "same one-line output.",
    "free": "Open the conversation. One short line, then one question worth "
            "answering. Same rules, same one-line output.",
}


def _system(mode: str, ctx: dict | None, topic: str, words: list[str]) -> str:
    if mode == "doc" and ctx:
        head = GROUND_DOC.format(passage=ctx["text"][:6000])
    elif mode == "topic":
        head = GROUND_TOPIC.format(topic=topic[:300])
    else:
        head = GROUND_FREE
    return head + RULES.format(level=config.LEVEL,
                               vocab=", ".join(words) or "(none saved yet)")


def _one_line(raw: str) -> str:
    line = ""
    for ln in raw.splitlines():
        s = ln.strip()
        if s.upper().startswith("REPLY:"):
            line = s[6:].strip()
            break
    if not line:
        line = re.sub(r"^\s*REPLY\s*:", "", raw.strip(), flags=re.I).strip()
        line = line.split("\n")[0].strip()
    return re.sub(r"[*_`#]", "", line).strip()[:900]


def _dev_open(mode: str, ctx: dict | None, topic: str) -> str:
    if mode == "doc" and ctx:
        return (f"So this section is about {ctx['title'] or 'the topic'}. "
                "What do you think its main claim is?")
    if mode == "topic":
        return f"Alright, {topic}. What got you interested in it?"
    return "No agenda then. What have you been chewing on this week?"


def _dev_reply(history: list[dict], words: list[str]) -> str:
    n = len([h for h in history if h["role"] == "learner"])
    w = words[n % len(words)] if words else "argument"
    canned = [
        f"That is a fair reading, though it leans on the {w} more than you said. "
        "Why do you think it holds?",
        "Fine, but you skipped the part that would make it fail. Where would it fail?",
        f"Right. Say more about the {w} — what would change your mind about it?",
    ]
    return canned[n % len(canned)]


def open_turn(mode: str, ctx: dict | None, topic: str, words: list[str]) -> str:
    if config.DEV:
        return _dev_open(mode, ctx, topic)
    msgs = [{"role": "system", "content": _system(mode, ctx, topic, words)},
            {"role": "user", "content": OPENERS.get(mode, OPENERS["free"])}]
    return _one_line(_chat(msgs, temperature=0.75))


def reply(mode: str, ctx: dict | None, topic: str, words: list[str],
          history: list[dict], said: str) -> str:
    if config.DEV:
        return _dev_reply(history + [{"role": "learner", "text": said}], words)
    msgs = [{"role": "system", "content": _system(mode, ctx, topic, words)}]
    for h in history[-config.TURNS_KEPT:]:
        msgs.append({"role": "assistant" if h["role"] == "tutor" else "user",
                     "content": h["text"]})
    msgs.append({"role": "user", "content": said})
    return _one_line(_chat(msgs))


# ------------------------------------------------------------------ the coach
COACH_PROMPT = """A second-language learner said this out loud in English:

"{said}"

Decide whether a teacher would correct it.

CORRECT only: grammar, verb tense and agreement, articles, prepositions, word
order, and word choice that changes the meaning.

NEVER "correct" any of the following. This was speech, and every one of these is
what fluent speech looks like:
- repeating a word or restarting a sentence ("Hello, hello", "I think — I mean")
- fillers, punctuation, capitalisation
- short answers and fragments, when a person would say them
- anything you would only change to make it more formal, longer or more elegant

If nothing in the CORRECT list is wrong, reply with exactly this and nothing else:
OK

Otherwise reply in exactly two lines and nothing else:
FIXED: their sentence corrected, with every word you changed or added wrapped in *asterisks*
WHY: 一句完整的中文，说明改动依据的语法规则，不要只给词义

Example of the WHY line: 主语是第三人称单数，动词要加 -s。
Not acceptable as a WHY line: a dictionary gloss, an English sentence, or a
translation of the corrected sentence."""


def coach(said: str) -> dict:
    """`{fixed, why}`, empty when the sentence was fine as spoken."""
    said = (said or "").strip()
    if len(said.split()) < 3:
        return {"fixed": "", "why": ""}
    if config.DEV:
        if "passage" in said.lower():
            return {"fixed": "I think the passage *is* mainly about how the method works.",
                    "why": "主语后缺少系动词 is。"}
        return {"fixed": "", "why": ""}
    try:
        raw = _chat([{"role": "user", "content": COACH_PROMPT.format(said=said[:600])}],
                    temperature=0.1, predict=160, timeout=90)
    except Exception:
        return {"fixed": "", "why": ""}
    if not raw.strip() or raw.strip().upper().startswith("OK"):
        return {"fixed": "", "why": ""}
    fixed, why = "", ""
    for ln in raw.splitlines():
        s = ln.strip()
        if s.upper().startswith("FIXED:"):
            fixed = s[6:].strip()
        elif s.upper().startswith("WHY:"):
            why = s[4:].strip()
    if not fixed:
        return {"fixed": "", "why": ""}
    # a "correction" identical to the original is the model hedging; drop it
    norm = lambda t: re.sub(r"[*\s.,!?'\"]", "", t).lower()   # noqa: E731
    if norm(fixed) == norm(said):
        return {"fixed": "", "why": ""}
    return {"fixed": fixed[:400], "why": why[:300]}


def stamp() -> float:
    return time.time()
