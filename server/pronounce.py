"""Pronunciation scoring.

The naive approach — compare the learner's waveform to the reference waveform —
measures timbre and speaking rate far more than pronunciation, so it is not used
here. Instead both recordings go through a *phoneme* CTC model and the two
phoneme strings are aligned:

    target   ð ɪ ŋ k        (from the Kokoro reference clip)
    heard    s ɪ ŋ k        (from the microphone)
                ^ substitution: ð -> s

Deriving the target from the reference *audio* rather than from a dictionary is
deliberate: both strings then come out of the same model in the same notation,
so no grapheme-to-phoneme component and no symbol mapping table is needed.

The score is alignment accuracy, which is deliberately blunt — it says whether
the sounds came out right, not how native the vowel quality was. Per-phoneme
detail is returned alongside so the number is never the only feedback.
"""
from __future__ import annotations

import importlib.util
import io
import threading

from . import config

TARGET_SR = 16000
_LOCK = threading.RLock()
_model = None
_proc = None
_device = "cpu"


def available() -> tuple[bool, str]:
    for m in ("transformers", "torch", "soundfile", "numpy"):
        if importlib.util.find_spec(m) is None:
            return False, f"missing {m}"
    return True, ""


def info() -> dict:
    ok, why = available()
    return {"available": ok, "reason": why, "model": config.ASR_MODEL,
            "loaded": _model is not None}


def _load():
    global _model, _proc, _device
    if _model is not None:
        return _proc, _model
    with _LOCK:
        if _model is None:
            from transformers import AutoModelForCTC, AutoProcessor
            _device = config.resolve_device()
            print(f"[gop] loading {config.ASR_MODEL} on {_device} …")
            _proc = AutoProcessor.from_pretrained(config.ASR_MODEL)
            _model = AutoModelForCTC.from_pretrained(config.ASR_MODEL).to(_device).eval()
    return _proc, _model


def unload() -> None:
    global _model, _proc
    with _LOCK:
        _model = None
        _proc = None
    try:
        import torch
        torch.cuda.empty_cache()
    except Exception:
        pass


def _read_mono16k(data: bytes):
    import numpy as np
    import soundfile as sf
    audio, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != TARGET_SR:                       # linear resample is fine for speech
        n = int(round(len(audio) * TARGET_SR / sr))
        audio = np.interp(np.linspace(0, len(audio) - 1, n),
                          np.arange(len(audio)), audio).astype("float32")
    peak = float(abs(audio).max()) if len(audio) else 0.0
    if peak > 0:
        audio = audio / peak * 0.95           # normalise: mic levels vary wildly
    return audio


def phonemes(wav_bytes: bytes) -> list[str]:
    import torch
    proc, model = _load()
    audio = _read_mono16k(wav_bytes)
    if len(audio) < TARGET_SR // 20:
        return []
    inputs = proc(audio, sampling_rate=TARGET_SR, return_tensors="pt")
    inputs = {k: v.to(_device) for k, v in inputs.items()}
    with torch.inference_mode():
        logits = model(**inputs).logits
    ids = logits.argmax(dim=-1)
    text = proc.batch_decode(ids)[0]
    return [p for p in text.split() if p]


# ------------------------------------------------------------------ alignment
def align(target: list[str], heard: list[str]) -> tuple[int, list[dict]]:
    """Needleman-Wunsch with unit costs; returns (distance, operations)."""
    n, m = len(target), len(heard)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = 0 if target[i - 1] == heard[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)

    ops: list[dict] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and d[i][j] == d[i - 1][j - 1] + (0 if target[i - 1] == heard[j - 1] else 1):
            same = target[i - 1] == heard[j - 1]
            ops.append({"op": "ok" if same else "sub",
                        "target": target[i - 1], "heard": heard[j - 1]})
            i, j = i - 1, j - 1
        elif i > 0 and d[i][j] == d[i - 1][j] + 1:
            ops.append({"op": "miss", "target": target[i - 1], "heard": ""})
            i -= 1
        else:
            ops.append({"op": "extra", "target": "", "heard": heard[j - 1]})
            j -= 1
    ops.reverse()
    return d[n][m], ops


def compare(user_wav: bytes, ref_wav: bytes) -> dict:
    target = phonemes(ref_wav)
    heard = phonemes(user_wav)
    if not heard:
        return {"ok": False, "error": "没听到声音，靠近麦克风再试一次"}
    if not target:
        return {"ok": False, "error": "参考音频异常"}

    dist, ops = align(target, heard)
    score = max(0, round(100 * (1 - dist / max(1, len(target)))))
    problems = [o for o in ops if o["op"] != "ok"]
    return {
        "ok": True,
        "score": score,
        "target": " ".join(target),
        "heard": " ".join(heard),
        "ops": ops,
        "problems": problems[:6],
    }
