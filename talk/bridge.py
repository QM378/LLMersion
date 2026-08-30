"""Borrow the reader's voice and its pronunciation scorer.

Both processes sit on the same machine and share the same data directory, so
when the reader is running there is no reason to load a second Kokoro and a
second wav2vec2 — that would be roughly 1.4 GB of duplicated weights for no
gain. This module calls the reader over loopback and reads the resulting audio
straight off the shared cache directory.

If the reader is not running, everything still works: the same calls are made
in-process against the same modules. Slower to start, identical output.
"""
from __future__ import annotations

import threading
import time

import requests

from . import config
from server import config as rc

_alive_at = 0.0
_alive = False
_LOCK = threading.RLock()

# True once the router has been mounted into the reader's own app. In that case
# the reader's Kokoro and wav2vec2 are already in *this* process: calling them
# over HTTP would mean a worker thread waiting on a response that needs another
# worker thread, which exhausts the pool and hangs the server. Call them
# directly instead — same objects, no socket, no deadlock.
IN_PROCESS = False


def set_in_process(value: bool = True) -> None:
    global IN_PROCESS
    IN_PROCESS = value


def reader_alive(ttl: float = 5.0) -> bool:
    """Cached liveness probe; the answer is only allowed to be 5 s stale."""
    global _alive, _alive_at
    if IN_PROCESS:
        return False          # we *are* the reader; never talk to ourselves
    now = time.time()
    with _LOCK:
        if now - _alive_at < ttl:
            return _alive
        try:
            r = requests.get(f"{config.READER_URL}/api/config", timeout=1.5)
            _alive = r.status_code == 200
        except Exception:
            _alive = False
        _alive_at = now
    return _alive


def _fname(url: str) -> str:
    return url.rsplit("/", 1)[-1]


# ------------------------------------------------------------------ voice
def speak(text: str) -> dict:
    """Synthesise one utterance. Returns `{fname, rate}`."""
    text = (text or "").strip()
    if not text:
        raise RuntimeError("nothing to say")

    if reader_alive():
        try:
            r = requests.post(f"{config.READER_URL}/api/tts",
                              json={"texts": [text]}, timeout=120)
            r.raise_for_status()
            item = (r.json().get("items") or [{}])[0]
            if item.get("ok"):
                return {"fname": _fname(item["url"]), "rate": item.get("rate", 1.0),
                        "via": "reader"}
        except Exception:
            pass  # fall through to the local path rather than losing the turn

    from server import tts
    out = tts.render(text)
    return {"fname": _fname(out["url"]), "rate": out.get("rate", 1.0),
            "via": "self" if IN_PROCESS else "local"}


def speak_block(text: str) -> dict:
    """Synthesise one turn and get back where each sentence starts and ends.

    The reader already solves this for paragraphs — it recovers sentence
    boundaries from the waveform rather than guessing proportionally — and the
    same call gives the window sentence-synchronised subtitles for free.
    Returns `{fname, rate, sents, marks}`; `marks` may be None if the engine
    could not be measured, in which case the caption simply does not follow.
    """
    from server import textseg
    text = (text or "").strip()
    if not text:
        raise RuntimeError("nothing to say")
    # split_sentences returns [{start, end, text}]; render_block wants the
    # strings, and so does the caption.
    sents = [s["text"] for s in textseg.split_sentences(text)] or [text]

    if reader_alive():
        try:
            r = requests.post(f"{config.READER_URL}/api/speak",
                              json={"blocks": [{"text": text, "sents": sents}]},
                              timeout=120)
            r.raise_for_status()
            item = (r.json().get("items") or [{}])[0]
            if item.get("ok"):
                return {"fname": _fname(item["url"]), "rate": item.get("rate", 1.0),
                        "sents": sents, "marks": item.get("marks"), "via": "reader"}
        except Exception:
            pass

    from server import tts
    out = tts.render_block(text, sents)
    return {"fname": _fname(out["url"]), "rate": out.get("rate", 1.0),
            "sents": sents, "marks": out.get("marks"),
            "via": "self" if IN_PROCESS else "local"}


# ------------------------------------------------------------------ scoring
# The reference is a synthetic American voice, so a learner who does not flap
# their /t/ or who lands a slightly different central vowel gets marked wrong
# for having a different accent rather than a worse one. These are the pairs
# where that happens most and where the distinction carries no meaning in
# English; folding them together is conservative — every pair below is a real
# allophone or a notation variant, not a contrast a learner needs to acquire.
_CLASSES = [
    "ɾtd",          # flap and stop: "what is" is ɾ in the reference, t from you
    "ɹrɻɚɝ",        # r colouring, however the model chose to write it
    "əɐʌɜ",         # central vowels, one phoneme's worth of variation
    "ɪi",
    "ʊu",
    "xh",           # breathy h heard as a velar fricative
    "ɡg",
    "oʊ",           # notation split for the same diphthong nucleus
]
_FOLD = {ch: row[0] for row in _CLASSES for ch in row}
_STRIP = str.maketrans("", "", "ːˈˌ̩ ")


def _norm(p: str) -> str:
    p = p.translate(_STRIP)
    return "".join(_FOLD.get(c, c) for c in p)


def _soften(result: dict) -> dict:
    """Re-read the alignment, forgiving accent-level differences."""
    ops = result.get("ops") or []
    if not ops:
        return result
    kept, wrong, targets = [], 0, 0
    for o in ops:
        op = o.get("op")
        if op in ("ok", "sub", "miss"):
            targets += 1
        if op == "sub" and _norm(o.get("target", "")) == _norm(o.get("heard", "")):
            kept.append({**o, "op": "ok", "folded": True})
            continue
        kept.append(o)
        if op != "ok":
            wrong += 1
    result["ops"] = kept
    result["problems"] = [o for o in kept if o["op"] != "ok"][:6]
    result["score"] = max(0, round(100 * (1 - wrong / max(1, targets))))
    return result


def score(wav: bytes, text: str) -> dict:
    """Phoneme-level score for a spoken turn against a synthesised reference.

    The reference is the learner's own transcript read by the voice they hear.
    That is an honest comparison for *articulation* — did the sounds come out —
    but note the loop it closes: if a word is mispronounced badly enough that
    the recogniser hears a different word, the reference becomes that other
    word and the error escapes the score. It catches slips, not systematic
    substitutions of one word for another.
    """
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "no transcript to score against"}

    if reader_alive():
        try:
            r = requests.post(f"{config.READER_URL}/api/pronounce",
                              files={"file": ("turn.wav", wav, "audio/wav")},
                              data={"word": text[:400]}, timeout=180)
            if r.status_code == 200:
                got = r.json()
                return _soften(got) if got.get("ok") else got
        except Exception:
            pass

    from server import pronounce, tts
    ok, why = pronounce.available()
    if not ok:
        return {"ok": False, "error": why}
    ref = tts.render(text[:400])
    ref_path = rc.AUDIO_DIR / _fname(ref["url"])
    try:
        got = pronounce.compare(wav, ref_path.read_bytes())
        return _soften(got) if got.get("ok") else got
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


# ------------------------------------------------------------------ status
def voice_info() -> dict:
    if reader_alive():
        try:
            d = requests.get(f"{config.READER_URL}/api/config", timeout=2).json()
            dv = d.get("tts", {}).get("default") or {}
            return {"available": bool(dv), "label": dv.get("label", ""),
                    "engine": dv.get("engine", ""), "via": "reader",
                    "gop": d.get("gop", {}).get("available", False)}
        except Exception:
            pass
    try:
        from server import pronounce, tts
        dv = tts.info().get("default") or {}
        return {"available": bool(dv), "label": dv.get("label", ""),
                "engine": dv.get("engine", ""),
                "via": "self" if IN_PROCESS else "local",
                "gop": pronounce.available()[0]}
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "label": "", "engine": "", "via": "none",
                "gop": False, "reason": str(exc)}
