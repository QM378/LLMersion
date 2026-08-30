"""Front door for every input format.

A loader returns the same shape as `pdf_parse.extract`: a title, a page count
and a list of paragraphs, each `{page, kind, text}`. `kind` drives the rest of
the app — `body` and `heading` are spoken, `other` and `toc` are shown but not.

Adding a format means adding a function here and one line in `LOADERS`.
"""
from __future__ import annotations

import html
import re
import zipfile
from pathlib import Path
from typing import Any, Callable

from . import pdf_parse
from .textseg import cjk_ratio

# Bump on any extraction change. Documents cached by an older version are
# re-parsed on open, so a fix reaches PDFs you have already read.
PARSER_VERSION = 5

CHARS_PER_PAGE = 1800          # only used to give text files a page count

_MD_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*\S)\s*#*\s*$")
_SETEXT = re.compile(r"^\s{0,3}(=+|-{2,})\s*$")
_TAG = re.compile(r"<[^>]+>")
_BLOCK_END = re.compile(r"</(p|div|h[1-6]|li|tr|section|article|blockquote)\s*>",
                        re.IGNORECASE)
_DROP = re.compile(r"<(script|style|head)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_HEADING_TAG = re.compile(r"<h[1-6]\b", re.IGNORECASE)
_LEADER = re.compile(r"(?:\.\s*){4,}")
_WS = re.compile(r"[ \t\u00a0]+")


def _finish(paras: list[dict], title: str) -> dict[str, Any]:
    out = []
    for p in paras:
        text = _WS.sub(" ", p["text"]).strip()
        if len(text) < 2:
            continue
        if _LEADER.search(text):
            p["kind"] = "toc"
            text = _LEADER.sub(" … ", text)
        elif cjk_ratio(text) > 0.25:
            p["kind"] = "cjk"
        p["text"] = text
        p["id"] = len(out)
        p.setdefault("page", 0)
        out.append(p)
    chars = sum(len(p["text"]) for p in out)
    return {
        "title": title or "Untitled",
        "pages": max(1, round(chars / CHARS_PER_PAGE)),
        "meta": {"source": "text"},
        "paragraphs": out,
    }


def _paginate(paras: list[dict]) -> None:
    """Text files have no pages; invent them so progress and jumping still work."""
    page, used = 0, 0
    for p in paras:
        if used and used + len(p["text"]) > CHARS_PER_PAGE:
            page += 1
            used = 0
        p["page"] = page
        used += len(p["text"])


# ------------------------------------------------------------------ plain text
def load_text(path: Path, filename: str) -> dict[str, Any]:
    raw = path.read_bytes()
    for enc in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            body = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        body = raw.decode("utf-8", "replace")

    body = body.replace("\r\n", "\n").replace("\r", "\n")
    if path.suffix.lower() in (".md", ".markdown"):
        # HTML comments are metadata (the curator writes provenance there);
        # they are not prose and must never reach the voice
        body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    lines = body.split("\n")

    paras: list[dict] = []
    buf: list[str] = []
    is_md = path.suffix.lower() in (".md", ".markdown")

    def flush() -> None:
        if buf:
            paras.append({"kind": "body", "text": " ".join(buf)})
            buf.clear()

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            flush()
            continue
        if is_md:
            m = _MD_HEADING.match(line)
            if m:
                flush()
                paras.append({"kind": "heading", "text": m.group(2)})
                continue
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if _SETEXT.match(nxt) and stripped:
                flush()
                paras.append({"kind": "heading", "text": stripped})
                continue
            if _SETEXT.match(line):
                continue
            if stripped.startswith(("```", "~~~")):
                flush()
                continue
        # a short line with no terminal punctuation, surrounded by blanks,
        # reads like a heading in a plain .txt too
        if (not buf and len(stripped) < 80 and stripped[-1] not in ".!?,;:"
                and (i + 1 >= len(lines) or not lines[i + 1].strip())):
            paras.append({"kind": "heading", "text": stripped})
            continue
        buf.append(stripped)
    flush()

    _paginate(paras)
    title = next((p["text"] for p in paras if p["kind"] == "heading"), "")
    return _finish(paras, title[:120] or Path(filename).stem)


# ------------------------------------------------------------------ html
def _html_to_paras(markup: str) -> list[dict]:
    markup = _DROP.sub(" ", markup)
    markup = re.sub(r"<br\s*/?>", "\n", markup, flags=re.IGNORECASE)
    paras: list[dict] = []
    pos = 0
    for m in _BLOCK_END.finditer(markup):
        chunk = markup[pos:m.end()]
        pos = m.end()
        kind = "heading" if _HEADING_TAG.search(chunk) else "body"
        text = html.unescape(_TAG.sub(" ", chunk))
        if text.strip():
            paras.append({"kind": kind, "text": text})
    tail = html.unescape(_TAG.sub(" ", markup[pos:]))
    if tail.strip():
        paras.append({"kind": "body", "text": tail})
    return paras


def load_html(path: Path, filename: str) -> dict[str, Any]:
    markup = path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"<title[^>]*>(.*?)</title>", markup, re.IGNORECASE | re.DOTALL)
    title = html.unescape(_TAG.sub("", m.group(1))).strip() if m else ""
    paras = _html_to_paras(markup)
    _paginate(paras)
    return _finish(paras, title or Path(filename).stem)


# ------------------------------------------------------------------ epub
def load_epub(path: Path, filename: str) -> dict[str, Any]:
    paras: list[dict] = []
    title = ""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        opf = next((n for n in names if n.lower().endswith(".opf")), None)
        order: list[str] = []
        if opf:
            spec = z.read(opf).decode("utf-8", "replace")
            m = re.search(r"<dc:title[^>]*>(.*?)</dc:title>", spec, re.DOTALL | re.IGNORECASE)
            if m:
                title = html.unescape(_TAG.sub("", m.group(1))).strip()
            base = str(Path(opf).parent)
            ids = dict(re.findall(r'<item\b[^>]*id="([^"]+)"[^>]*href="([^"]+)"', spec))
            for ref in re.findall(r'<itemref\b[^>]*idref="([^"]+)"', spec):
                href = ids.get(ref)
                if not href:
                    continue
                full = str(Path(base) / href) if base not in (".", "") else href
                full = full.replace("\\", "/")
                if full in names:
                    order.append(full)
        if not order:
            order = [n for n in names
                     if n.lower().endswith((".xhtml", ".html", ".htm"))]
        for name in order:
            try:
                paras.extend(_html_to_paras(z.read(name).decode("utf-8", "replace")))
            except Exception:  # noqa: BLE001
                continue
    _paginate(paras)
    return _finish(paras, title or Path(filename).stem)


# ------------------------------------------------------------------ dispatch
def load_pdf(path: Path, filename: str) -> dict[str, Any]:
    return pdf_parse.extract(str(path))


LOADERS: dict[str, Callable[[Path, str], dict[str, Any]]] = {
    ".pdf": load_pdf,
    ".txt": load_text,
    ".text": load_text,
    ".md": load_text,
    ".markdown": load_text,
    ".html": load_html,
    ".htm": load_html,
    ".epub": load_epub,
}

EXTENSIONS = sorted(LOADERS)


def load(path: Path, filename: str) -> dict[str, Any]:
    ext = Path(filename).suffix.lower() or path.suffix.lower()
    fn = LOADERS.get(ext)
    if fn is None:
        raise ValueError(f"unsupported file type '{ext}' — try {', '.join(EXTENSIONS)}")
    parsed = fn(path, filename)
    parsed.setdefault("meta", {})["parser"] = PARSER_VERSION
    return parsed
