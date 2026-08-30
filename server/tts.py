"""Caching layer in front of the engine registry.

Engines produce bytes; this module decides what to synthesise, what to reuse and
where it lives on disk. The cache key is content-addressed over engine, voice,
speed and text — so switching voices to compare two accents never re-renders the
one you already heard, and switching back is instant.

Engines that cannot change rate (`supports_speed = False`) drop speed from the
key entirely and report a `rate` for the browser to apply as playbackRate. One
render serves every speed.
"""
from __future__ import annotations

from . import cache, config
from .engines import MANAGER, Voice
from .textseg import strip_cjk


def info() -> dict:
    d = MANAGER.default_voice()
    return {
        "engines": MANAGER.status(),
        "voices": [v.as_dict() for v in MANAGER.voices()],
        "default": d.as_dict() if d else None,
        "voices_dir": str(config.VOICES_DIR),
    }


def resolve(engine_id: str = "", voice_id: str = "") -> Voice:
    if engine_id and voice_id:
        return MANAGER.find(engine_id, voice_id)
    d = MANAGER.default_voice()
    if d is None:
        raise RuntimeError("no usable TTS engine — see the engine list in settings")
    return d


def render(text: str, engine_id: str = "", voice_id: str = "",
           speed: float = 1.0) -> dict:
    """Return {url, rate, engine, voice}, synthesising only on a cache miss."""
    text = strip_cjk(text)
    if not text.strip():
        raise RuntimeError("nothing for an English voice to read here")
    v = resolve(engine_id, voice_id)
    from .engines import REGISTRY
    engine_cls = REGISTRY[v.engine]

    server_speed = speed if engine_cls.supports_speed else 1.0
    client_rate = 1.0 if engine_cls.supports_speed else speed

    key = cache.sha1(v.engine, v.id, f"{server_speed:.2f}", text)
    hit = cache.get_audio(key)
    fname = hit["fname"] if hit else None
    if fname is None:
        data = MANAGER.synth(text, v, server_speed)
        if not data:
            raise RuntimeError("engine returned no audio")
        fname = f"{key}.{engine_cls.ext}"
        tmp = config.AUDIO_DIR / (fname + ".part")
        tmp.write_bytes(data)
        tmp.rename(config.AUDIO_DIR / fname)
        cache.put_audio(key, fname, v.engine)
    return {"url": f"/api/audio/{fname}", "rate": client_rate,
            "engine": v.engine, "voice": v.id}


def render_block(text: str, sents: list[str], engine_id: str = "",
                 voice_id: str = "", speed: float = 1.0) -> dict:
    """One paragraph -> one audio file plus per-sentence boundaries.

    Falls back down the chain in `blocks`: paragraph-in-one-pass with detected
    pauses, then per-sentence with exact joins, then proportional estimates.
    """
    from . import blocks
    from .engines import REGISTRY

    v = resolve(engine_id, voice_id)
    engine_cls = REGISTRY[v.engine]
    # a Chinese run inside an English paragraph (a citation, a quoted term) is
    # dropped rather than handed to an English voice
    sents = [strip_cjk(s) for s in sents]
    sents = [s for s in sents if s.strip()] or [strip_cjk(text)]
    text = strip_cjk(text)
    if not text.strip():
        raise RuntimeError("nothing for an English voice to read here")

    server_speed = speed if engine_cls.supports_speed else 1.0
    client_rate = 1.0 if engine_cls.supports_speed else speed
    # the unit is part of the key: the same paragraph renders differently when
    # synthesised whole vs sentence by sentence, and both are worth keeping
    key = cache.sha1(v.engine, v.id, f"{server_speed:.2f}", config.TTS_UNIT, text)

    hit = cache.get_audio(key)
    if hit and hit["marks"]:
        return {"url": f"/api/audio/{hit['fname']}", "rate": client_rate,
                "marks": hit["marks"], "method": hit["method"],
                "engine": v.engine, "voice": v.id}

    ext = engine_cls.ext
    data: bytes | None = None
    marks = None
    method = ""

    can_open = ext == "wav" and _have_audio_libs()

    if config.TTS_UNIT == "paragraph":
        whole = MANAGER.synth(text, v, server_speed)
        if whole:
            if can_open and len(sents) > 1:
                got = blocks.split_by_silence(whole, sents)
                if got:
                    data, (marks, method) = whole, got
            elif len(sents) == 1:
                data, marks, method = whole, [[0.0, 1.0]], "split"
            if data is None and not can_open:
                data = whole
                marks, method = blocks.estimate(sents)

    if data is None:
        clips = [MANAGER.synth(s, v, server_speed) for s in sents]
        clips = [c for c in clips if c]
        if not clips:
            raise RuntimeError("engine returned no audio")
        if can_open:
            data, marks, method = blocks.concat(clips, sents)
        else:
            data = clips[0] if len(clips) == 1 else b"".join(clips)
            marks, method = blocks.estimate(sents)

    fname = f"{key}.{ext}"
    tmp = config.AUDIO_DIR / (fname + ".part")
    tmp.write_bytes(data)
    tmp.rename(config.AUDIO_DIR / fname)
    cache.put_audio(key, fname, v.engine, marks, method)
    return {"url": f"/api/audio/{fname}", "rate": client_rate,
            "marks": marks, "method": method, "engine": v.engine, "voice": v.id}


def _have_audio_libs() -> bool:
    import importlib.util
    return all(importlib.util.find_spec(m) for m in ("numpy", "soundfile"))
