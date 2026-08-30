"""Turn a paragraph into one audio file plus per-sentence boundaries.

Why a paragraph and not a sentence: neural TTS predicts prosody over a whole
utterance. Synthesising sentence by sentence throws away every cross-sentence
cue — each sentence restarts at a neutral pitch and the paragraph ends up
sounding like a list rather than someone reading. Generating the paragraph in
one pass keeps the contour continuous and lets the model place its own pauses.

That costs us the sentence timings the highlighter needs, so we get them back
one of three ways, in order of preference:

  split     the model's own pauses are found in the waveform and matched to
            the sentence boundaries we expect from the text
  concat    synthesise per sentence and join with measured pauses — timings are
            exact by construction, prosody is the old behaviour
  estimate  proportional to character counts; used for engines that hand back
            compressed audio we cannot open

Boundaries are returned as fractions of total duration, which keeps them valid
whatever playback rate the client applies.
"""
from __future__ import annotations

import io

# pauses inserted by `concat`, in seconds
PAUSE_END = 0.30      # after . ! ?
PAUSE_MID = 0.16      # after , ; :
LEAD_IN = 0.05

SILENCE_MIN = 0.09    # a gap must last this long to count as a sentence break
FRAME = 0.010         # RMS analysis hop


def _np():
    import numpy as np
    return np


def char_weights(sents: list[str]) -> list[float]:
    n = [max(1, len(s)) for s in sents]
    total = float(sum(n))
    out, acc = [], 0.0
    for c in n:
        out.append((acc / total, (acc + c) / total))
        acc += c
    return out


def estimate(sents: list[str]) -> tuple[list[list[float]], str]:
    return [[a, b] for a, b in char_weights(sents)], "estimate"


def _read(wav_bytes: bytes):
    import soundfile as sf
    data, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32", always_2d=False)
    np = _np()
    if data.ndim > 1:
        data = data.mean(axis=1)
    return np.asarray(data, dtype="float32"), sr


def _write(audio, sr: int) -> bytes:
    import soundfile as sf
    buf = io.BytesIO()
    sf.write(buf, audio, sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def _rms(audio, sr: int):
    np = _np()
    hop = max(1, int(sr * FRAME))
    n = len(audio) // hop
    if n < 2:
        return np.zeros(1, dtype="float32"), hop
    frames = audio[: n * hop].reshape(n, hop)
    return np.sqrt((frames ** 2).mean(axis=1) + 1e-12), hop


def _silence_runs(audio, sr: int) -> list[tuple[float, float]]:
    """Return [(start_s, end_s)] of gaps long enough to be sentence breaks."""
    np = _np()
    rms, hop = _rms(audio, sr)
    if len(rms) < 4:
        return []
    floor = max(float(np.percentile(rms, 10)) * 2.5, float(rms.max()) * 0.02)
    quiet = rms < floor
    runs, start = [], None
    for i, q in enumerate(quiet):
        if q and start is None:
            start = i
        elif not q and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(quiet)))
    sec = hop / sr
    return [(a * sec, b * sec) for a, b in runs if (b - a) * sec >= SILENCE_MIN]


def split_by_silence(wav_bytes: bytes, sents: list[str]) -> tuple[list[list[float]], str] | None:
    """Match the model's own pauses to the sentence boundaries we expect."""
    if len(sents) == 1:
        return [[0.0, 1.0]], "split"
    try:
        audio, sr = _read(wav_bytes)
    except Exception:
        return None
    total = len(audio) / sr
    if total < 0.4:
        return None

    gaps = _silence_runs(audio, sr)
    # drop leading and trailing silence, they are not sentence breaks
    inner = [g for g in gaps if g[0] > total * 0.02 and g[1] < total * 0.98]
    if len(inner) < len(sents) - 1:
        return None

    want = [b for a, b in char_weights(sents)][:-1]      # expected split points
    centres = [(a + b) / 2 / total for a, b in inner]
    chosen: list[float] = []
    used: set[int] = set()
    for w in want:
        best, bestd = -1, 1e9
        for i, c in enumerate(centres):
            if i in used:
                continue
            d = abs(c - w)
            if d < bestd:
                best, bestd = i, d
        # a boundary more than 12% of the paragraph away from where the text
        # says it should be means the match has gone wrong; bail out entirely
        if best < 0 or bestd > 0.12:
            return None
        used.add(best)
        chosen.append(centres[best])
    chosen.sort()
    if any(b <= a for a, b in zip(chosen, chosen[1:])):
        return None

    marks, prev = [], 0.0
    for c in chosen + [1.0]:
        marks.append([prev, c])
        prev = c
    return marks, "split"


def _trim(audio, sr: int):
    """Strip padding silence so joined clips do not gape."""
    np = _np()
    rms, hop = _rms(audio, sr)
    if len(rms) < 3:
        return audio
    floor = max(float(rms.max()) * 0.03, 1e-4)
    loud = np.where(rms > floor)[0]
    if len(loud) == 0:
        return audio
    keep = int(0.02 * sr)
    a = max(0, loud[0] * hop - keep)
    b = min(len(audio), (loud[-1] + 1) * hop + keep)
    return audio[a:b]


def concat(clips: list[bytes], sents: list[str]) -> tuple[bytes, list[list[float]], str]:
    """Join per-sentence clips with human-length pauses; timings are exact."""
    np = _np()
    pieces, sr = [], None
    for wav in clips:
        audio, rate = _read(wav)
        sr = sr or rate
        pieces.append(_trim(audio, rate))

    out = [np.zeros(int(sr * LEAD_IN), dtype="float32")]
    bounds = []
    cursor = LEAD_IN
    for piece, text in zip(pieces, sents):
        dur = len(piece) / sr
        bounds.append((cursor, cursor + dur))
        out.append(piece)
        gap = PAUSE_END if text.rstrip()[-1:] in ".!?" else PAUSE_MID
        out.append(np.zeros(int(sr * gap), dtype="float32"))
        cursor += dur + gap

    audio = np.concatenate(out)
    total = len(audio) / sr
    marks = [[a / total, b / total] for a, b in bounds]
    return _write(audio, sr), marks, "concat"
