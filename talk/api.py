"""HTTP surface for conversation practice.

Everything lives under /api/talk/ and the router has no dependency on how it is
served, so the same file backs the standalone window today and a one-line
`include_router` inside the reader later.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from . import bridge, config, dialogue, stt, store
from server import cache

router = APIRouter(prefix="/api/talk", tags=["talk"])
POOL = ThreadPoolExecutor(max_workers=12)
# `turn` hands its whole body to a worker and that worker submits two more,
# so the pool has to be comfortably wider than the number of concurrent turns.

# mode/topic/anchor per session, so a turn does not have to re-read the row
_SESS: dict[str, dict] = {}


def _sess(session: str) -> dict:
    if session in _SESS:
        return _SESS[session]
    row = store.conn().execute(
        "SELECT mode,topic,doc_id,para FROM session WHERE id=?", (session,)).fetchone()
    if not row:
        raise HTTPException(404, "session not found — start a new one")
    _SESS[session] = {"mode": row["mode"] or "free", "topic": row["topic"] or "",
                      "doc_id": row["doc_id"] or "", "para": row["para"] or 0}
    return _SESS[session]


def _context(s: dict):
    if s["mode"] != "doc" or not s["doc_id"]:
        return None
    try:
        return dialogue.passage(s["doc_id"], s["para"])
    except KeyError:
        return None


# ------------------------------------------------------------------ status
@router.get("/health")
def health() -> dict:
    return {
        "stt": stt.info(),
        "llm": dialogue.llm_info(),
        "voice": bridge.voice_info(),
        "reader": {"url": config.READER_URL, "alive": bridge.reader_alive()},
        "dev": config.DEV,
        "score_default": config.SCORE_DEFAULT,
        "coach_default": config.COACH,
        "interim_default": config.INTERIM,
        "level": config.LEVEL,
    }


@router.get("/docs")
def docs() -> dict:
    items = cache.list_docs(40)
    for d in items:
        d["progress"] = cache.get_progress(d["doc_id"])
    return {"items": items,
            "vocab": len([v for v in cache.list_vocab(400) if not v.get("known")])}


@router.post("/stt/unload")
def stt_unload() -> dict:
    stt.unload()
    return {"ok": True}


# ------------------------------------------------------------------ session
@router.post("/session")
def start(payload: dict = Body(...)) -> dict:
    mode = (payload.get("mode") or "free").strip()
    if mode not in dialogue.MODES:
        mode = "free"
    topic = (payload.get("topic") or "").strip()
    doc_id = (payload.get("doc_id") or "").strip()
    para = payload.get("para")

    if mode == "topic" and not topic:
        raise HTTPException(400, "写一句想聊什么")
    ctx = None
    if mode == "doc":
        if not doc_id:
            raise HTTPException(400, "选一份文档")
        try:
            ctx = dialogue.passage(doc_id, None if para is None else int(para))
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    words = dialogue.target_words()
    sid = uuid.uuid4().hex[:12]
    store.new_session(sid, mode, doc_id if ctx else "", ctx["title"] if ctx else "",
                      ctx["para"] if ctx else 0, topic)
    _SESS[sid] = {"mode": mode, "topic": topic,
                  "doc_id": doc_id if ctx else "", "para": ctx["para"] if ctx else 0}

    t0 = time.time()
    try:
        text = dialogue.open_turn(mode, ctx, topic, words)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"对话模型没有响应：{exc.__class__.__name__}") from exc

    used = dialogue.used_words(text, words)
    store.add_turn(sid, "tutor", text, used, secs=round(time.time() - t0, 2))

    out = {"session": sid, "mode": mode, "topic": topic, "targets": words,
           "context": ({k: ctx[k] for k in ("doc_id", "title", "para", "from", "to",
                                            "words", "total")} if ctx else None),
           "excerpt": ctx["text"][:1200] if ctx else "",
           "turn": {"role": "tutor", "text": text, "used": used}}
    out["turn"].update(_voice(text))
    return out


@router.post("/anchor")
def anchor(payload: dict = Body(...)) -> dict:
    """Re-point an open document conversation at wherever the learner has read to."""
    sid = payload.get("session", "")
    s = _sess(sid)
    if s["mode"] != "doc":
        return {"ok": False, "reason": "not a document conversation"}
    para = int(payload.get("para", 0))
    s["para"] = para
    store.conn().execute("UPDATE session SET para=? WHERE id=?", (para, sid))
    store.conn().commit()
    ctx = dialogue.passage(s["doc_id"], para)
    return {"ok": True,
            "context": {k: ctx[k] for k in ("doc_id", "title", "para", "from", "to",
                                            "words")},
            "excerpt": ctx["text"][:1200]}


@router.get("/session/{sid}")
def session(sid: str) -> dict:
    return {"turns": store.history(sid), "stats": store.stats(sid)}


@router.get("/sessions")
def sessions() -> dict:
    return {"items": store.sessions()}


# ------------------------------------------------------------------ a turn
def _voice(text: str) -> dict:
    try:
        v = bridge.speak_block(text)
        return {"audio": f"/api/talk/audio/{v['fname']}", "rate": v["rate"],
                "sents": v["sents"], "marks": v["marks"]}
    except Exception as exc:  # noqa: BLE001
        return {"audio": "", "rate": 1.0, "sents": [text], "marks": None,
                "voice_error": str(exc)}


def _interim(wav: bytes) -> dict:
    try:
        return {"text": stt.transcribe(wav)["text"]}
    except Exception:
        return {"text": ""}


@router.post("/interim")
async def interim(file: UploadFile = File(...)) -> dict:
    """Transcribe what has been said *so far*, while the learner keeps talking.

    Nothing is stored and no model beyond the recogniser is touched: this exists
    only so the words appear as they are spoken instead of arriving in a lump.
    Recognition runs on a worker thread — this fires every second and a half,
    and doing it on the event loop would stall every other request that often.
    """
    if not config.INTERIM or not stt.info()["available"]:
        return {"text": ""}
    wav = await file.read()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(POOL, _interim, wav)


@router.post("/turn")
async def turn(session: str = Form(...),
               text: str = Form(""),
               score: int = Form(1),
               coach: int = Form(1),
               file: Optional[UploadFile] = File(None)) -> dict:
    """One exchange: what the learner said in, what the tutor says back out."""
    wav = await file.read() if file is not None else b""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        POOL, _do_turn, session, text, int(score), int(coach), wav)


def _do_turn(session: str, text: str, score: int, coach: int, wav: bytes) -> dict:
    """Recognition has to finish before anything else can start, but the three
    jobs that follow do not depend on each other — the reply, the correction and
    the pronunciation score all read the same transcript. They run together, so
    the turn costs the slowest of them rather than their sum.
    """
    s = _sess(session)
    t0 = time.time()
    said = text.strip()
    stt_secs = 0.0
    if not said:
        if not wav:
            raise HTTPException(400, "say something or type something")
        if not stt.info()["available"]:
            raise HTTPException(503, "没有可用的语音识别 — 见 talk/README.md")
        try:
            got = stt.transcribe(wav)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"识别失败：{exc}") from exc
        said, stt_secs = got["text"], got["secs"]
    if not said:
        return {"empty": True, "message": "没听清，靠近麦克风再说一次"}

    ctx = _context(s)
    words = dialogue.target_words()
    hist = store.history(session)

    fut_score = POOL.submit(bridge.score, wav, said) if (score and wav) else None
    fut_coach = (POOL.submit(dialogue.coach, said)
                 if (coach and config.COACH) else None)

    try:
        reply_text = dialogue.reply(s["mode"], ctx, s["topic"], words, hist, said)
    except Exception as exc:  # noqa: BLE001
        for f in (fut_score, fut_coach):
            if f:
                f.cancel()
        raise HTTPException(503, f"对话模型没有响应：{exc.__class__.__name__}") from exc

    spoken = dialogue.used_words(said, words)
    tutor_used = dialogue.used_words(reply_text, words)

    scored = None
    if fut_score:
        try:
            got = fut_score.result(timeout=120)
            scored = got if got.get("ok") else None
        except Exception:
            scored = None
    fixed = {"fixed": "", "why": ""}
    if fut_coach:
        try:
            fixed = fut_coach.result(timeout=120)
        except Exception:
            pass

    store.add_turn(session, "learner", said, spoken,
                   scored["score"] if scored else None,
                   fixed["fixed"], fixed["why"], stt_secs)
    store.add_turn(session, "tutor", reply_text, tutor_used,
                   secs=round(time.time() - t0, 2))

    out = {
        "learner": {"role": "learner", "text": said, "used": spoken,
                    "fixed": fixed["fixed"], "why": fixed["why"],
                    "score": scored["score"] if scored else None,
                    "problems": (scored or {}).get("problems", []),
                    "stt_secs": stt_secs},
        "turn": {"role": "tutor", "text": reply_text, "used": tutor_used},
        "targets": words,
        "stats": store.stats(session),
        "secs": round(time.time() - t0, 2),
    }
    out["turn"].update(_voice(reply_text))
    return out


@router.post("/say")
def say(payload: dict = Body(...)) -> dict:
    """Read any text with the reader's voice — replay, or a single word."""
    return _voice((payload.get("text") or "").strip()[:600])


@router.get("/audio/{fname}")
def audio(fname: str):
    """Serve from the shared cache directory, wherever the file was made."""
    path = (config.AUDIO_DIR / fname).resolve()
    if config.AUDIO_DIR.resolve() not in path.parents or not path.exists():
        raise HTTPException(404, "audio not found")
    media = "audio/mpeg" if path.suffix == ".mp3" else "audio/wav"
    return FileResponse(path, media_type=media,
                        headers={"Cache-Control": "public, max-age=604800"})


@router.get("/words")
def words() -> dict:
    """Target words with how often they have actually been said out loud."""
    spoken = store.word_history()
    return {"items": [{"word": w, "spoken": spoken.get(w, 0)}
                      for w in dialogue.target_words(40)]}
