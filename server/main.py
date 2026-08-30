"""HTTP API + static frontend."""
from __future__ import annotations

import hashlib
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import cache, config, dictionary, llm, loaders, pronounce, textseg, translate, tts

app = FastAPI(title="LLMersion-1")


@app.middleware("http")
async def gate(request, call_next):
    """Optional shared-secret gate, off unless PR_TOKEN is set."""
    if config.TOKEN:
        given = (request.query_params.get("token")
                 or request.headers.get("x-reader-token")
                 or request.cookies.get("reader_token", ""))
        if given != config.TOKEN:
            return JSONResponse({"detail": "bad or missing token"}, status_code=401)
        response = await call_next(request)
        response.set_cookie("reader_token", config.TOKEN, max_age=30 * 86400,
                            samesite="lax")
        return response
    return await call_next(request)
POOL = ThreadPoolExecutor(max_workers=4)
WEB = config.ROOT / "web"


# ------------------------------------------------------------------ meta
@app.get("/api/config")
def api_config() -> dict:
    return {
        "tts": tts.info(),
        "mt": translate.info(),
        "dict": {"available": dictionary.available()},
        "speed": config.TTS_SPEED,
        "unit": config.TTS_UNIT,
        "formats": loaders.EXTENSIONS,
        "gop": pronounce.info(),
    }


@app.post("/api/rescan")
def api_rescan() -> dict:
    """Re-read models/voices and models/tts after you drop new files in."""
    from .engines import MANAGER as TTS_MANAGER
    from .mt import MANAGER as MT_MANAGER
    TTS_MANAGER._checks.clear()
    MT_MANAGER.refresh()
    return api_config()


@app.post("/api/unit")
def api_unit(payload: dict = Body(...)) -> dict:
    """Switch between paragraph-at-once and sentence-at-a-time synthesis."""
    unit = payload.get("unit", "paragraph")
    if unit not in ("paragraph", "sentence"):
        raise HTTPException(400, "unit must be paragraph or sentence")
    config.TTS_UNIT = unit
    return {"ok": True, "unit": unit}


@app.post("/api/tts/unload")
def api_tts_unload() -> dict:
    from .engines import MANAGER as TTS_MANAGER
    TTS_MANAGER.unload_all()
    return {"ok": True}


@app.get("/api/docs")
def api_docs() -> dict:
    return {"items": cache.list_docs()}


# ------------------------------------------------------------------ document
@app.post("/api/open")
async def api_open(file: UploadFile = File(...)) -> dict:
    raw = await file.read()
    name = file.filename or "document.pdf"
    ext = Path(name).suffix.lower()
    if ext not in loaders.LOADERS:
        raise HTTPException(400, f"Unsupported file type '{ext}'. "
                                 f"Supported: {', '.join(loaders.EXTENSIONS)}")
    doc_id = hashlib.sha1(raw).hexdigest()[:16]
    path = config.DOCS_DIR / f"{doc_id}{ext}"
    if not path.exists():
        path.write_bytes(raw)

    cached = cache.get_doc(doc_id)
    stale = cached is not None and cached["meta"].get("parser") != loaders.PARSER_VERSION
    if stale:
        print(f"[open] re-parsing {doc_id}: parser "
              f"{cached['meta'].get('parser')} -> {loaders.PARSER_VERSION}")
    if cached is None or stale:
        try:
            parsed = loaders.load(path, name)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"Could not read this file: {exc}") from exc
        if not parsed["paragraphs"]:
            msg = ("No selectable text found. This looks like a scanned PDF — run OCR first."
                   if ext == ".pdf" else "No text found in this file.")
            raise HTTPException(400, msg)
        title = parsed["title"] or Path(name).stem
        cache.put_doc(doc_id, title, parsed["pages"], parsed["meta"], parsed["paragraphs"])
        cached = cache.get_doc(doc_id)

    for p in cached["paragraphs"]:
        if "sents" not in p:
            p["sents"] = textseg.split_sentences(p["text"])
    cached["progress"] = cache.get_progress(doc_id)
    return cached


@app.get("/api/doc/{doc_id}")
def api_doc(doc_id: str) -> dict:
    d = cache.get_doc(doc_id)
    if not d:
        raise HTTPException(404, "Document not found")
    for p in d["paragraphs"]:
        p["sents"] = textseg.split_sentences(p["text"])
    d["progress"] = cache.get_progress(doc_id)
    return d


@app.get("/api/doc/{doc_id}/file")
def api_doc_file(doc_id: str):
    hit = next(iter(config.DOCS_DIR.glob(f"{doc_id}.*")), None)
    if hit is None:
        raise HTTPException(404, "File not found")
    return FileResponse(hit)


# ------------------------------------------------------------------ tts
@app.post("/api/tts")
def api_tts(payload: dict = Body(...)) -> dict:
    texts: list[str] = [t for t in payload.get("texts", []) if t and t.strip()]
    engine: str = payload.get("engine", "")
    voice: str = payload.get("voice", "")
    speed: float = float(payload.get("speed", config.TTS_SPEED))
    if not texts:
        return {"items": []}

    def one(t: str) -> dict:
        try:
            return {"ok": True, **tts.render(t, engine, voice, speed)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    return {"items": list(POOL.map(one, texts))}


@app.post("/api/speak")
def api_speak(payload: dict = Body(...)) -> dict:
    """Paragraph-level synthesis: one file per block, with sentence marks."""
    engine: str = payload.get("engine", "")
    voice: str = payload.get("voice", "")
    speed: float = float(payload.get("speed", config.TTS_SPEED))
    blocks_in: list[dict] = payload.get("blocks", [])

    def one(b: dict) -> dict:
        try:
            return {"ok": True, **tts.render_block(b.get("text", ""), b.get("sents", []),
                                                   engine, voice, speed)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    return {"items": list(POOL.map(one, blocks_in))}


@app.get("/api/audio/{fname}")
def api_audio(fname: str):
    path = (config.AUDIO_DIR / fname).resolve()
    if config.AUDIO_DIR.resolve() not in path.parents or not path.exists():
        raise HTTPException(404, "Audio not found")
    media = "audio/mpeg" if path.suffix == ".mp3" else "audio/wav"
    return FileResponse(path, media_type=media,
                        headers={"Cache-Control": "public, max-age=604800"})


# ------------------------------------------------------------------ translation
@app.post("/api/translate")
def api_translate(payload: dict = Body(...)) -> dict:
    texts: list[str] = payload.get("texts", [])
    if not texts:
        return {"items": []}
    try:
        return {"items": translate.translate(texts, payload.get("backend", ""),
                                             payload.get("model", ""))}
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"items": ["" for _ in texts], "error": str(exc)}, status_code=200)


# ------------------------------------------------------------------ dictionary
@app.get("/api/lookup")
def api_lookup(q: str = Query(..., min_length=1, max_length=200)) -> dict:
    return dictionary.lookup(q)


# ------------------------------------------------------------------ progress + vocab
@app.post("/api/progress")
def api_progress(payload: dict = Body(...)) -> dict:
    doc_id = payload.get("doc_id")
    if not doc_id:
        raise HTTPException(400, "doc_id required")
    cache.set_progress(doc_id, int(payload.get("para", 0)), int(payload.get("sent", 0)))
    return {"ok": True}


@app.post("/api/writing")
def api_writing(payload: dict):
    """LLM feedback on learner writing, aware of their active vocabulary."""
    text = (payload.get("text") or "").strip()
    if len(text) < 20:
        return {"error": "写一段再来 — 至少几句话。"}
    if not llm.available():
        return {"error": "需要 Ollama 在运行（用于写作反馈）。启动 Ollama 后重试。"}
    words = [v["word"] for v in cache.list_vocab(200) if not v.get("known")][:30]
    prompt = llm.WRITE_PROMPT.format(vocab=", ".join(words) or "(none saved yet)",
                                     text=text[:4000])
    try:
        return {"feedback": llm.chat(prompt)}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"LLM 调用失败: {exc.__class__.__name__}"}


@app.post("/api/simplify")
def api_simplify(payload: dict):
    """Re-render one paragraph at an easier difficulty, on request."""
    text = (payload.get("text") or "").strip()
    if not text:
        return {"error": "empty"}
    if not llm.available():
        return {"error": "需要 Ollama 在运行（用于简化改写）。"}
    try:
        return {"text": llm.chat(llm.SIMPLIFY_PROMPT.format(text=text[:3000]),
                                 temperature=0.2)}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"LLM 调用失败: {exc.__class__.__name__}"}


@app.post("/api/pronounce")
async def api_pronounce(file: UploadFile = File(...), word: str = Form(...),
                        engine: str = Form(""), voice: str = Form("")) -> dict:
    """Score a recording of `word` against the TTS reference for the same word."""
    ok, why = pronounce.available()
    if not ok:
        raise HTTPException(400, f"发音评分不可用：{why}")
    user_wav = await file.read()
    ref = tts.render(word, engine, voice, 1.0)
    ref_path = config.AUDIO_DIR / ref["url"].split("/")[-1]
    try:
        result = pronounce.compare(user_wav, ref_path.read_bytes())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"评分失败：{exc}") from exc
    if result.get("ok"):
        cache.record_score(word, result["score"])
    return result


@app.post("/api/pronounce/unload")
def api_pronounce_unload() -> dict:
    pronounce.unload()
    return {"ok": True}


@app.get("/api/vocab")
def api_vocab_list() -> dict:
    return {"items": cache.list_vocab()}


@app.post("/api/vocab")
def api_vocab_add(payload: dict = Body(...)) -> dict:
    cache.add_vocab(payload["word"], payload.get("zh", ""), payload.get("phonetic", ""),
                    payload.get("context", ""), payload.get("doc_id", ""))
    return {"ok": True}


@app.post("/api/vocab/merge")
def api_vocab_merge() -> dict:
    return cache.merge_vocab(dictionary.base_form)


@app.post("/api/vocab/known")
def api_vocab_known(payload: dict = Body(...)) -> dict:
    cache.set_known(payload["word"], int(payload.get("known", 1)))
    return {"ok": True}


@app.get("/api/vocab/export.csv")
def api_vocab_export():
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["word", "phonetic", "zh", "context", "added", "hits", "known"])
    for r in cache.list_vocab():
        w.writerow([r["word"], r["phonetic"], (r["zh"] or "").replace("\n", " / "),
                    r["context"], time.strftime("%Y-%m-%d", time.localtime(r["ts"] or 0)),
                    r["hits"], r["known"]])
    return Response(buf.getvalue().encode("utf-8-sig"), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="vocab.csv"'})


@app.delete("/api/vocab/{word}")
def api_vocab_del(word: str) -> dict:
    cache.del_vocab(word)
    return {"ok": True}


# ------------------------------------------------------------------ talk
# The conversation module is optional: if talk/ is not there, or its own
# dependencies are missing, the reader loads exactly as before and the button
# in the toolbar hides itself. Mounted before the catch-all below, because the
# first matching mount wins.
TALK_WEB = config.ROOT / "talk" / "web"
HAS_TALK = False
try:
    if TALK_WEB.exists():
        from talk import bridge as talk_bridge
        from talk.api import router as talk_router
        talk_bridge.set_in_process(True)   # voice and scorer are already here
        app.include_router(talk_router)
        app.mount("/talk", StaticFiles(directory=TALK_WEB, html=True), name="talk")
        HAS_TALK = True
except Exception as exc:  # noqa: BLE001
    print(f"[talk] not loaded: {exc.__class__.__name__}: {exc}")


@app.get("/api/talk-available")
def api_talk_available() -> dict:
    return {"available": HAS_TALK}


# ------------------------------------------------------------------ static
if WEB.exists():
    app.mount("/", StaticFiles(directory=WEB, html=True), name="web")


def banner() -> None:
    """Print what is and is not available, so a missing piece is obvious."""
    print("\n  LLMersion-1")
    print(f"  {'-' * 58}")
    t = tts.info()
    for e in t["engines"]:
        mark = "ok " if e["available"] else "-- "
        detail = f"{e['voices']} voices" if e["available"] else f"{e['reason']}"
        print(f"  {mark}{e['label']:<22} {detail}")
        if not e["available"] and e["notes"]:
            print(f"     {' ' * 22} {e['notes']}")
    d = t["default"]
    print(f"  {'-' * 58}")
    print(f"  voice      {d['label'] + ' (' + d['engine'] + ')' if d else 'NONE — reading will not work'}")
    m = translate.info()
    md = m["default"]
    if md["model"]:
        print(f"  translate  {md['model']} via {md['backend']}")
    else:
        reasons = "; ".join(f"{b['id']}: {b['reason']}" for b in m["backends"] if not b["available"])
        print(f"  translate  NONE — {reasons}")
    print(f"  dictionary {'ECDICT' if dictionary.available() else 'NONE — run tools/build_ecdict.py'}")
    print(f"  talk       {'ready — 工具栏「对话」' if HAS_TALK else 'not installed'}")
    print(f"  data       {config.DATA}")
    print(f"  {'-' * 58}")
    where = "127.0.0.1" if config.HOST == "0.0.0.0" else config.HOST
    suffix = f"/?token={config.TOKEN}" if config.TOKEN else ""
    print(f"  http://{where}:{config.PORT}{suffix}")
    if not config.is_local():
        print(f"  bound to {config.HOST} — reachable from other machines"
              + ("" if config.TOKEN else "  ⚠ no PR_TOKEN set"))
        print("  microphone scoring needs HTTPS or an SSH tunnel; see DEPLOY.md")
    print()


def main() -> None:
    import threading
    import uvicorn
    import webbrowser

    banner()
    # a remote host has no browser to open, and no display to open it on
    if os.environ.get("PR_NO_OPEN") != "1" and config.is_local():
        url = f"http://{config.HOST}:{config.PORT}"
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    # quiet by default; PR_LOG=info shows every request, which is the fastest
    # way to tell "the browser is not talking to me" from "synthesis is slow"
    uvicorn.run(app, host=config.HOST, port=config.PORT,
                log_level=os.environ.get("PR_LOG", "warning"))


if __name__ == "__main__":
    main()
