"""Turn whatever the browser sent into 16 kHz mono float32.

The browser writes a plain WAV header over raw samples rather than using
MediaRecorder, so nothing here needs ffmpeg — soundfile reads it directly.
"""
from __future__ import annotations

import io

SR = 16000


def read_mono16k(data: bytes):
    import numpy as np
    import soundfile as sf

    audio, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != SR:
        n = int(round(len(audio) * SR / sr))
        audio = np.interp(np.linspace(0, len(audio) - 1, n),
                          np.arange(len(audio)), audio).astype("float32")
    peak = float(abs(audio).max()) if len(audio) else 0.0
    if peak > 0:
        audio = audio / peak * 0.95
    return audio


def duration(data: bytes) -> float:
    try:
        import soundfile as sf
        info = sf.info(io.BytesIO(data))
        return float(info.frames) / float(info.samplerate or SR)
    except Exception:
        return 0.0
