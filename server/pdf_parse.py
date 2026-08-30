"""PDF -> clean, reflowed paragraphs.

Design notes
------------
* Only text blocks are kept (``block["type"] == 0``); images/figures never enter
  the pipeline, so an illustrated PDF degrades to "text only" instead of breaking.
* Running headers/footers are detected statistically: a normalised string that
  shows up in the top/bottom margin band on many pages is furniture, not content.
* Two-column layouts are detected per page and re-ordered left-column-first.
* Paragraphs are merged across block and page boundaries when the previous chunk
  does not look finished (no terminal punctuation + next chunk starts lowercase).
"""
from __future__ import annotations

import re
import statistics
from collections import Counter
from typing import Any

try:
    import pymupdf as fitz          # PyMuPDF >= 1.24
except ImportError:                 # pragma: no cover
    import fitz                     # older wheels

# Bump when extraction changes; cached documents parsed by an older version are
# re-parsed on open instead of silently serving stale text.
PARSER_VERSION = 5

HEADER_BAND = 0.075          # fraction of page height treated as margin
MIN_REPEAT_RATIO = 0.25      # repeat rate above which a margin line is furniture
LETTER_RATIO_BODY = 0.55     # below this a block is "other" (tables/formulas)

_WS = re.compile(r"[ \t]+")
# ". . . . . . 17"  or  "........ 17" — a contents line, never a sentence
_LEADER = re.compile(r"(?:\.\s*){4,}")
_BAD = "\ufffd"          # what MuPDF emits for a glyph with no Unicode mapping

# Subset fonts often ship ligatures with no ToUnicode entry. Which ligature it
# was is unrecoverable from the PDF, but in English prose the candidates are few
# and this covers the words that actually occur in technical writing.
_LIG_WORDS = {
    # each word belongs to exactly one list — a word appearing twice would make
    # the lookup ambiguous and pick whichever was inserted first
    "fi": ("modified", "specific", "specifically", "verifiable", "verified", "verify",
           "classifier", "classification", "define", "defined", "definition",
           "field", "fields", "final", "finally", "finding", "findings", "first",
           "fixed", "benefit", "benefits", "confidence", "configuration",
           "significant", "significantly", "identify", "identified", "identifier",
           "quantified", "unified", "simplified", "amplified", "notify", "profile",
           "figure", "figures", "file", "files", "filter", "filtered", "fine",
           "confirm", "confirmed", "artifact", "artifacts", "profit", "confident",
           "justified", "specification", "finetuning", "refine", "refined"),
    "fl": ("reflect", "reflects", "reflected", "flow", "flows", "float", "floating",
           "flag", "flags", "flat", "flexible", "influence", "influenced",
           "conflict", "inflation", "workflow", "overflow", "flip", "fluctuation"),
    "ff": ("offer", "offers", "offered", "effect", "effects", "effective",
           "effectively", "different", "difference", "differences", "differently",
           "staff", "off", "offset", "buffer", "suffix", "affect", "affected",
           "traffic", "diffusion", "differ", "differs", "effort", "efforts"),
    "ffi": ("efficient", "efficiently", "efficiency", "sufficient", "sufficiently",
            "insufficient", "difficult", "difficulty", "difficulties",
            "coefficient", "coefficients", "official", "affinity"),
    "ffl": ("baffled", "shuffled", "reshuffle", "conflated"),
}
_LIG_LOOKUP: dict[str, str] = {}
for _lig, _words in _LIG_WORDS.items():
    for _w in _words:
        _LIG_LOOKUP.setdefault(_w, _lig)


def _repair_word(word: str) -> str:
    """Guess what a replacement character inside a word used to be."""
    for lig in ("fi", "ffi", "fl", "ff", "ffl"):
        if _LIG_LOOKUP.get(word.replace(_BAD, lig).lower()) == lig:
            return word.replace(_BAD, lig)
    # nothing matched: "fi" is by far the most common ligature in English
    return word.replace(_BAD, "fi")


def _repair(text: str) -> str:
    if _BAD not in text:
        return text
    out = []
    for tok in re.split(r"(\s+)", text):
        if _BAD not in tok:
            out.append(tok)
            continue
        core = tok.strip("\"'()[[]{},.;:")
        if core == _BAD:
            # a standalone box is punctuation the font could not map: a dash
            out.append(tok.replace(_BAD, "—"))
        elif re.search(r"[A-Za-z]" + _BAD + r"[A-Za-z]", tok):
            out.append(_repair_word(tok))
        elif tok.startswith(_BAD):
            out.append(tok.replace(_BAD, "\u201c", 1))     # opening quote
        elif tok.endswith(_BAD):
            out.append(tok[:-1] + "\u201d")                # closing quote
        else:
            out.append(tok.replace(_BAD, ""))
        out.append("")
    return "".join(out[:-1] if out and out[-1] == "" else out)
_HYPHEN_BREAK = re.compile(r"([A-Za-z])[-\u2010\u2011]\n([a-z])")
_SOFT_BREAK = re.compile(r"(?<![.\n])\n(?!\n)")
_NUM = re.compile(r"\d+")


def _norm_key(s: str) -> str:
    return _NUM.sub("#", _WS.sub(" ", s.strip().lower()))[:80]


def _letter_ratio(s: str) -> float:
    if not s:
        return 0.0
    return sum(ch.isalpha() or ch.isspace() for ch in s) / len(s)


def _block_text(b: dict) -> tuple[str, float, float, int]:
    """Return (text, median font size, bold char ratio, char count)."""
    lines: list[str] = []
    sizes: list[float] = []
    bold = 0
    total = 0
    for ln in b.get("lines", []):
        d = ln.get("dir", (1, 0))
        if abs(d[1]) > 0.1:            # rotated / vertical text -> skip
            continue
        buf = []
        for sp in ln.get("spans", []):
            t = sp.get("text", "")
            if not t:
                continue
            buf.append(t)
            n = len(t)
            total += n
            sizes.append(sp.get("size", 0.0))
            font = sp.get("font", "").lower()
            if "bold" in font or "black" in font or (sp.get("flags", 0) & 16):
                bold += n
        s = "".join(buf).strip()
        if s:
            lines.append(s)
    text = "\n".join(lines)
    size = statistics.median(sizes) if sizes else 0.0
    return text, size, (bold / total if total else 0.0), total


def _collect_blocks(doc: "fitz.Document") -> list[dict]:
    out = []
    for pno in range(len(doc)):
        page = doc[pno]
        rect = page.rect
        # PRESERVE_LIGATURES keeps "ﬁ" as one glyph, which shows up as a box
        # whenever the font has no ToUnicode entry for it. Turn it off and let
        # MuPDF expand ligatures to plain letters.
        flags = (fitz.TEXTFLAGS_DICT
                 & ~fitz.TEXT_PRESERVE_LIGATURES
                 & ~fitz.TEXT_PRESERVE_IMAGES)
        raw = page.get_text("dict", flags=flags)
        for b in raw.get("blocks", []):
            if b.get("type", 0) != 0:      # 1 == image
                continue
            text, size, boldr, nch = _block_text(b)
            if not text.strip():
                continue
            x0, y0, x1, y1 = b["bbox"]
            out.append({
                "page": pno, "bbox": [x0, y0, x1, y1], "text": text,
                "size": size, "bold": boldr, "nch": nch,
                "pw": rect.width, "ph": rect.height,
            })
    return out


def _strip_furniture(blocks: list[dict], npages: int) -> list[dict]:
    counts: Counter[str] = Counter()
    for b in blocks:
        top = b["bbox"][1] < b["ph"] * HEADER_BAND
        bot = b["bbox"][3] > b["ph"] * (1 - HEADER_BAND)
        if (top or bot) and len(b["text"]) <= 120:
            counts[_norm_key(b["text"])] += 1
    threshold = max(3, int(npages * MIN_REPEAT_RATIO))
    bad = {k for k, v in counts.items() if v >= threshold and k}
    kept = []
    for b in blocks:
        top = b["bbox"][1] < b["ph"] * HEADER_BAND
        bot = b["bbox"][3] > b["ph"] * (1 - HEADER_BAND)
        if top or bot:
            k = _norm_key(b["text"])
            if k in bad or re.fullmatch(r"[#\s\-–—|/.]*", k or ""):
                continue
        kept.append(b)
    return kept


def _order_page(blocks: list[dict]) -> list[dict]:
    """Reading order for one page; handles the common two-column case."""
    if len(blocks) < 4:
        return sorted(blocks, key=lambda b: (round(b["bbox"][1], 1), b["bbox"][0]))
    pw = blocks[0]["pw"]
    mid = pw / 2
    narrow = [b for b in blocks if (b["bbox"][2] - b["bbox"][0]) < pw * 0.60]
    left = [b for b in narrow if b["bbox"][2] <= mid + pw * 0.04]
    right = [b for b in narrow if b["bbox"][0] >= mid - pw * 0.04]
    two_col = len(left) >= 2 and len(right) >= 2 and (len(left) + len(right)) >= len(blocks) * 0.6
    if not two_col:
        return sorted(blocks, key=lambda b: (round(b["bbox"][1], 1), b["bbox"][0]))

    def col(b: dict) -> int:
        w = b["bbox"][2] - b["bbox"][0]
        if w >= pw * 0.60:                     # full-width (title / figure caption)
            return 0 if b["bbox"][1] < blocks[0]["ph"] * 0.3 else 1
        return 0 if (b["bbox"][0] + b["bbox"][2]) / 2 < mid else 1

    return sorted(blocks, key=lambda b: (col(b), round(b["bbox"][1], 1)))


def _clean(text: str) -> str:
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    text = _SOFT_BREAK.sub(" ", text)
    text = text.replace("\n", " ")
    text = _WS.sub(" ", text)
    for lig, plain in (("ﬁ", "fi"), ("ﬂ", "fl"), ("ﬀ", "ff"), ("ﬃ", "ffi"),
                       ("ﬄ", "ffl"), ("ﬅ", "st"), ("ﬆ", "st"), ("æ", "ae"),
                       ("Æ", "AE"), ("œ", "oe"), ("Œ", "OE")):
        text = text.replace(lig, plain)
    text = _LEADER.sub(" … ", text)
    text = _repair(text)
    return text.strip()


def _kind(text: str, size: float, body: float, bold: float, raw: str = "") -> str:
    # check the raw text: _clean has already collapsed the leaders by now
    if _LEADER.search(raw or text) or " … " in text:
        return "toc"
    if _letter_ratio(text) < LETTER_RATIO_BODY:
        return "other"
    short = len(text) < 200
    if short and (size >= body * 1.12 or (bold > 0.7 and len(text) < 120)):
        return "heading"
    return "body"


def _mergeable(prev: dict, cur: dict) -> bool:
    if prev["kind"] != "body" or cur["kind"] != "body":
        return False
    a, b = prev["text"], cur["text"]
    if not a or not b:
        return False
    if a[-1] in ".!?\u3002\u201d\"')]:;":
        return False
    if not (b[0].islower() or b[0] in ",;)"):
        return False
    if abs(prev["size"] - cur["size"]) > 0.6:
        return False
    return True


def extract(path: str) -> dict[str, Any]:
    doc = fitz.open(path)
    npages = len(doc)
    blocks = _collect_blocks(doc)
    blocks = _strip_furniture(blocks, npages)

    ordered: list[dict] = []
    for pno in range(npages):
        ordered.extend(_order_page([b for b in blocks if b["page"] == pno]))

    if ordered:
        body_size = statistics.median(
            [b["size"] for b in ordered for _ in range(max(1, b["nch"] // 20))]
        )
    else:
        body_size = 10.0

    paras: list[dict] = []
    for b in ordered:
        text = _clean(b["text"])
        if not text:
            continue
        kind = _kind(text, b["size"], body_size, b["bold"], raw=b["text"])
        cur = {"page": b["page"], "kind": kind, "text": text,
               "size": b["size"], "bbox": [round(v, 1) for v in b["bbox"]]}
        if paras and _mergeable(paras[-1], cur):
            paras[-1]["text"] = paras[-1]["text"].rstrip() + " " + text
            paras[-1]["bbox"] = None            # merged: layout box no longer meaningful
        else:
            paras.append(cur)

    out = []
    for i, p in enumerate(paras):
        if len(p["text"]) < 2:
            continue
        p.pop("size", None)
        p["id"] = len(out)
        out.append(p)

    md = doc.metadata or {}
    title = (md.get("title") or "").strip()
    if not title or len(title) < 3:
        head = next((p["text"] for p in out if p["kind"] == "heading"), "")
        title = head[:120] or "Untitled"
    doc.close()
    return {
        "title": title,
        "pages": npages,
        "meta": {"author": (md.get("author") or "").strip(), "body_size": body_size,
                 "parser": PARSER_VERSION},
        "paragraphs": out,
    }
