"""Sentence segmentation with character offsets (needed for karaoke highlight).

blingfire is a ~5x faster, better-behaved splitter than a hand-rolled regex; if it
is not installed we fall back to a regex that knows the usual academic abbreviations.
"""
from __future__ import annotations

import re

try:
    from blingfire import text_to_sentences as _bf
except Exception:  # pragma: no cover
    _bf = None

MAX_CHARS = 260   # long sentences get sub-split so TTS latency stays low

# CJK ideographs, kana, Hangul, and full-width punctuation
_CJK = re.compile(
    r"[\u3000-\u303f\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff"
    r"\uf900-\ufaff\uff00-\uffef\uac00-\ud7af]"
)


def cjk_ratio(text: str) -> float:
    """Share of non-space characters that are CJK."""
    body = [c for c in text if not c.isspace()]
    if not body:
        return 0.0
    return sum(bool(_CJK.match(c)) for c in body) / len(body)


def strip_cjk(text: str) -> str:
    """Remove CJK before synthesis: an English voice cannot say it, and what it
    does instead is worse than silence."""
    return re.sub(r"\s{2,}", " ", _CJK.sub(" ", text)).strip()

_ABBR = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "fig", "eq",
    "ref", "sec", "ch", "no", "vol", "al", "e.g", "i.e", "cf", "approx", "inc",
    "ltd", "co", "univ", "dept", "pp", "ph.d", "u.s", "u.k", "resp", "cd", "ed",
}
# a sentence-ending punctuation cluster followed by whitespace and a capital/digit
_RE_CAND = re.compile(r"([.!?][\"'\u201d\u2019)\]]*)(\s+)(?=[\"'\u201c(\[]*[A-Z0-9])")
_RE_CJK_END = re.compile(r"(?<=[\u3002\uff01\uff1f])")
_RE_TAIL = re.compile(r"([A-Za-z.]+)$")
_RE_SUB = re.compile(r"(?<=[,;:])\s+")


def _is_abbrev(text: str, dot_pos: int) -> bool:
    m = _RE_TAIL.search(text[:dot_pos])
    if not m:
        return False
    tok = m.group(1).rstrip(".").lower()
    return tok in _ABBR or (len(tok) == 1 and tok.isalpha())


def _sub_split(s: str, base: int) -> list[tuple[int, int, str]]:
    if len(s) <= MAX_CHARS:
        return [(base, base + len(s), s)]
    out, start = [], 0
    for m in _RE_SUB.finditer(s):
        if m.end() - start >= MAX_CHARS * 0.6:
            out.append((base + start, base + m.start(), s[start:m.start()]))
            start = m.end()
    tail = s[start:]
    if tail.strip():
        out.append((base + start, base + len(s), tail))
    return out or [(base, base + len(s), s)]


def split_sentences(text: str) -> list[dict]:
    """Return [{start, end, text}] with offsets into `text`."""
    text = text.strip()
    if not text:
        return []

    spans: list[tuple[int, int, str]] = []
    if _bf is not None:
        cursor = 0
        for line in _bf(text).split("\n"):
            line = line.strip()
            if not line:
                continue
            idx = text.find(line[:24], cursor)
            if idx < 0:
                idx = cursor
            end = idx + len(line)
            spans.append((idx, min(end, len(text)), text[idx:min(end, len(text))]))
            cursor = end
    else:
        start = 0
        for m in _RE_CAND.finditer(text):
            if _is_abbrev(text, m.start(1)):
                continue
            end = m.end(1)
            chunk = text[start:end]
            if chunk.strip():
                spans.append((start, end, chunk))
            start = m.end(2)
        if text[start:].strip():
            spans.append((start, len(text), text[start:]))

    if not spans:
        spans = [(0, len(text), text)]

    out: list[dict] = []
    for s, e, t in spans:
        for a, b, chunk in _sub_split(t, s):
            chunk = chunk.strip()
            if chunk:
                out.append({"start": a, "end": b, "text": chunk})
    return out
