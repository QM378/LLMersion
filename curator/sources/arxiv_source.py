"""arXiv as a nightly source.

Uses the official export API (Atom feed; no key). By default the curator
prepares the *abstract plus introduction-sized excerpt* from the PDF when the
reader's PDF pipeline is importable, and falls back to abstract-only when it is
not -- the curator must remain runnable standalone.

arXiv asks automated clients to be gentle: one query per run, results reused,
and a descriptive User-Agent.
"""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from pathlib import Path

API = "https://export.arxiv.org/api/query"
UA = {"User-Agent": "ReadingDeskCurator/1.0 (open-source study tool)"}
NS = {"a": "http://www.w3.org/2005/Atom"}


def parse_feed(xml_text: str) -> list[dict]:
    """Atom -> [{'id','title','summary','pdf_url','published'}]. Split out for
    testing without the network."""
    out = []
    root = ET.fromstring(xml_text)
    for e in root.findall("a:entry", NS):
        raw_id = e.findtext("a:id", "", NS)             # http://arxiv.org/abs/2401.01234v1
        short = raw_id.rsplit("/", 1)[-1]
        pdf = ""
        for link in e.findall("a:link", NS):
            if link.get("title") == "pdf" or link.get("type") == "application/pdf":
                pdf = link.get("href", "")
        out.append({
            "id": f"arxiv:{short}",
            "title": " ".join((e.findtext("a:title", "", NS) or "").split()),
            "summary": " ".join((e.findtext("a:summary", "", NS) or "").split()),
            "pdf_url": pdf,
            "url": raw_id,
        })
    return out


def search(topic: str, limit: int = 8) -> list[dict]:
    import requests
    params = {"search_query": f'all:"{topic}"', "sortBy": "submittedDate",
              "sortOrder": "descending", "max_results": limit}
    r = requests.get(API, params=params, headers=UA, timeout=30)
    r.raise_for_status()
    time.sleep(3)                                       # arXiv's requested pause
    return parse_feed(r.text)


def fetch(entry: dict, max_pdf_pages: int = 30) -> dict:
    """Build paragraphs for one paper. Tries the reader's PDF pipeline for the
    full text; degrades to the abstract alone."""
    paras = [{"kind": "heading", "text": "Abstract"},
             {"kind": "body", "text": entry["summary"]}]
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from server import loaders                       # reader present? bonus.
        import requests, tempfile
        pdf = requests.get(entry["pdf_url"], headers=UA, timeout=120)
        pdf.raise_for_status()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(pdf.content)
            tmp = Path(f.name)
        doc = loaders.load(tmp, entry["title"] + ".pdf")
        tmp.unlink(missing_ok=True)
        body = [p for p in doc["paragraphs"]
                if p["kind"] in ("body", "heading")]
        if doc.get("pages", 0) <= max_pdf_pages and len(body) > 4:
            paras = body
    except Exception as exc:  # noqa: BLE001 -- abstract-only is a fine outcome
        print(f"  (abstract only: {exc.__class__.__name__})")
    return {"id": entry["id"], "title": entry["title"], "url": entry["url"],
            "paragraphs": paras}
