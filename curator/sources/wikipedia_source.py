"""Wikipedia as a nightly source.

Uses only the public MediaWiki action API (no key, no scraping): full-text
search to map a topic to an article, plain-text extraction, and `morelike:`
search for related articles -- the curator's discovery channel.

Licensing: Wikipedia text is CC BY-SA. Every generated file carries the source
URL and an attribution line, and the share-alike condition is inherited by the
prepared Markdown; the README states this plainly.
"""
from __future__ import annotations

import urllib.parse

API = "https://en.wikipedia.org/w/api.php"
UA = {"User-Agent": "ReadingDeskCurator/1.0 (open-source study tool)"}


def _get(params: dict) -> dict:
    import requests
    params = {"format": "json", "formatversion": "2", **params}
    r = requests.get(API, params=params, headers=UA, timeout=30)
    r.raise_for_status()
    return r.json()


def search(topic: str, limit: int = 5) -> list[dict]:
    """Top article candidates for a topic: [{'id','title'}]."""
    data = _get({"action": "query", "list": "search", "srsearch": topic,
                 "srlimit": limit, "srnamespace": 0})
    return [{"id": f"wiki:{h['pageid']}", "title": h["title"]}
            for h in data.get("query", {}).get("search", [])]


def related(title: str, limit: int = 8) -> list[str]:
    """Titles similar to `title` via CirrusSearch morelike -- exploration fuel."""
    data = _get({"action": "query", "list": "search",
                 "srsearch": f"morelike:{title}", "srlimit": limit})
    return [h["title"] for h in data.get("query", {}).get("search", [])]


def fetch(title: str) -> dict:
    """Plain-text article -> {'title','url','paragraphs':[{'kind','text'}]}."""
    data = _get({"action": "query", "prop": "extracts", "explaintext": 1,
                 "titles": title, "redirects": 1})
    page = data["query"]["pages"][0]
    text = page.get("extract", "")
    url = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(page["title"].replace(" ", "_"))
    paras: list[dict] = []
    for chunk in text.split("\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if chunk.startswith("==") and chunk.endswith("=="):
            head = chunk.strip("= ").strip()
            # boilerplate tails add nothing to reading practice
            if head.lower() in ("see also", "references", "external links",
                                "further reading", "notes", "bibliography"):
                break
            paras.append({"kind": "heading", "text": head})
        elif len(chunk) > 60:                      # skip stub lines and captions
            paras.append({"kind": "body", "text": chunk})
    return {"id": f"wiki:{page['pageid']}", "title": page["title"],
            "url": url, "paragraphs": paras}
