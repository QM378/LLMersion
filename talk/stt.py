"""Local speech recognition.

Three interchangeable backends, picked in order of cost:

    faster-whisper   CTranslate2, int8 — fastest and lightest, needs an install
    transformers     already present in this project for translation and the
                     pronunciation scorer, so `base.en` costs no new dependency
    openai-whisper   the reference implementation, if you already have it

The model is loaded on first use and can be dropped again, which is what keeps
the "under 2 GB resident" claim honest: nothing is held while you are only
reading. `base.en` is about 145 MB and transcribes a learner's ten-second turn
in well under a second on any recent GPU, and in a second or two on a laptop
CPU.
"""
from __future__ import annotations

import importlib.util
import threading
import time

from . import audio, config
from server import config as rc

_LOCK = threading.RLock()
_backend = ""      # id of the backend currently loaded
_handle = None     # whatever that backend needs to keep
_device = "cpu"


def _have(mod: str) -> bool:
    return importlib.util.find_spec(mod) is not None


def candidates() -> list[dict]:
    """Every backend and whether it could run right now."""
    out = [
        {"id": "faster-whisper", "label": "faster-whisper (int8)",
         "available": _have("faster_whisper"),
         "reason": "" if _have("faster_whisper") else "pip install faster-whisper",
         "note": "fastest, lowest memory"},
        {"id": "transformers", "label": "Whisper via transformers",
         "available": _have("transformers") and _have("torch"),
         "reason": "" if (_have("transformers") and _have("torch")) else "needs transformers + torch",
         "note": "no new dependency — this project already installs both"},
        {"id": "openai-whisper", "label": "openai-whisper",
         "available": _have("whisper"),
         "reason": "" if _have("whisper") else "pip install openai-whisper",
         "note": "reference implementation"},
    ]
    if config.DEV:
        out.insert(0, {"id": "dev", "label": "dev (no model)", "available": True,
                       "reason": "", "note": "canned transcript, for UI testing"})
    return out


def pick() -> str:
    if config.DEV:
        return "dev"
    if config.STT_BACKEND != "auto":
        return config.STT_BACKEND
    for c in candidates():
        if c["available"] and c["id"] != "dev":
            return c["id"]
    return ""


def info() -> dict:
    chosen = pick()
    known = {c["id"]: c for c in candidates()}
    ok = bool(chosen) and known.get(chosen, {}).get("available", False)
    return {
        "available": ok,
        "backend": chosen,
        "model": config.STT_MODEL,
        "loaded": _handle is not None,
        "device": _device if _handle is not None else rc.resolve_device(),
        "reason": "" if ok else "no speech recogniser installed — see talk/README.md",
        "backends": candidates(),
    }


# ------------------------------------------------------------------ loading
def _load():
    global _handle, _backend, _device
    if _handle is not None:
        return _handle
    with _LOCK:
        if _handle is not None:
            return _handle
        chosen = pick()
        if not chosen:
            raise RuntimeError("no speech recogniser available")
        t0 = time.time()

        if chosen == "dev":
            _handle, _backend, _device = "dev", "dev", "cpu"

        elif chosen == "faster-whisper":
            from faster_whisper import WhisperModel
            dev = rc.resolve_device()
            dev = "cuda" if dev == "cuda" else "cpu"       # no Metal in CTranslate2
            compute = "int8_float16" if dev == "cuda" else "int8"
            print(f"[stt] loading faster-whisper {config.STT_MODEL} on {dev} ({compute}) …")
            _handle = WhisperModel(config.STT_MODEL, device=dev, compute_type=compute,
                                   download_root=str(config.STT_DIR))
            _backend, _device = chosen, dev

        elif chosen == "transformers":
            import torch
            from transformers import WhisperForConditionalGeneration, WhisperProcessor
            name = config.hf_name(config.STT_MODEL)
            dev = rc.resolve_device()
            print(f"[stt] loading {name} on {dev} …")
            proc = WhisperProcessor.from_pretrained(name)
            model = WhisperForConditionalGeneration.from_pretrained(name)
            try:
                model = model.to(dev)
            except Exception as exc:                        # incomplete Metal kernels
                print(f"[stt] {dev} refused the model ({exc.__class__.__name__}); using CPU")
                dev = "cpu"
                model = model.to(dev)
            model.eval()
            _handle = (proc, model)
            _backend, _device = chosen, dev
            del torch

        elif chosen == "openai-whisper":
            import whisper
            dev = rc.resolve_device()
            dev = dev if dev in ("cuda", "cpu") else "cpu"
            print(f"[stt] loading openai-whisper {config.STT_MODEL} on {dev} …")
            _handle = whisper.load_model(config.STT_MODEL, device=dev,
                                         download_root=str(config.STT_DIR))
            _backend, _device = chosen, dev
        else:
            raise RuntimeError(f"unknown STT backend '{chosen}'")

        print(f"[stt] ready in {time.time() - t0:.1f}s")
    return _handle


def unload() -> None:
    global _handle, _backend
    with _LOCK:
        _handle = None
        _backend = ""
    try:
        import torch
        torch.cuda.empty_cache()
    except Exception:
        pass


# ------------------------------------------------------------------ decoding
def transcribe(wav: bytes) -> dict:
    """Bytes of a WAV in, `{text, secs, backend}` out."""
    t0 = time.time()
    h = _load()

    if _backend == "dev":
        time.sleep(0.3)
        return {"text": "I think the passage is mainly about how the method works.",
                "secs": round(time.time() - t0, 2), "backend": "dev"}

    pcm = audio.read_mono16k(wav)
    if len(pcm) < audio.SR * 0.25:
        return {"text": "", "secs": 0.0, "backend": _backend}

    if _backend == "faster-whisper":
        segments, _ = h.transcribe(pcm, language="en", beam_size=1,
                                   vad_filter=True, condition_on_previous_text=False)
        text = " ".join(s.text.strip() for s in segments).strip()

    elif _backend == "transformers":
        import torch
        proc, model = h
        feats = proc(pcm, sampling_rate=audio.SR, return_tensors="pt").input_features
        feats = feats.to(_device)
        # An English-only checkpoint (`.en`) rejects `language`/`task` outright;
        # a multilingual one needs them or it will happily transcribe a Chinese
        # speaker's English into Chinese.
        kw = {} if config.STT_MODEL.endswith(".en") else {"language": "en",
                                                          "task": "transcribe"}
        with torch.inference_mode():
            try:
                ids = model.generate(feats, **kw)
            except ValueError:
                ids = model.generate(feats)
        text = proc.batch_decode(ids, skip_special_tokens=True)[0].strip()

    else:  # openai-whisper
        out = h.transcribe(pcm, language="en", fp16=(_device == "cuda"),
                           condition_on_previous_text=False)
        text = (out.get("text") or "").strip()

    return {"text": text, "secs": round(time.time() - t0, 2), "backend": _backend}
