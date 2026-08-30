"""A tone generator that pretends to be a voice. Off unless PR_DEV=1.

Useful for working on the reader, the scheduler or the UI without downloading a
model, and for CI. It also serves as the smallest possible worked example of an
engine, including a cloning-style voice list.
"""
from __future__ import annotations

import io
import math
import os
import struct
import wave

from . import register
from .base import TTSEngine, Voice, clone_voices_for

SR = 22050


@register
class DevEngine(TTSEngine):
    id = "dev"
    label = "Dev tone (testing)"
    ext = "wav"
    supports_cloning = True
    supports_speed = True
    rank = 999
    notes = "set PR_DEV=1 to enable"

    @classmethod
    def check(cls) -> tuple[bool, str]:
        if os.environ.get("PR_DEV") != "1":
            return False, "set PR_DEV=1 to enable"
        return True, ""

    @classmethod
    def list_voices(cls) -> list[Voice]:
        base = [
            Voice(id="low", label="Dev tone · low", engine=cls.id, gender="male",
                  params={"f0": 110}),
            Voice(id="high", label="Dev tone · high", engine=cls.id, gender="female",
                  params={"f0": 220}),
        ]
        return base + clone_voices_for(cls.id)

    def synth(self, text: str, voice: Voice, speed: float) -> bytes:
        f0 = float((voice.params or {}).get("f0", 160))
        rate = max(0.3, speed)
        frames = bytearray()

        def tone(seconds: float, freq: float) -> None:
            n = int(SR * seconds)
            for i in range(n):
                t = i / SR
                env = min(1.0, t / 0.008) * min(1.0, (seconds - t) / 0.012)
                v = 0.25 * env * math.sin(2 * math.pi * freq * t)
                frames.extend(struct.pack("<h", int(v * 32767)))

        def hush(seconds: float) -> None:
            frames.extend(b"\x00\x00" * int(SR * seconds))

        # one blip per word, a real pause after sentence-ending punctuation,
        # so the silence-based boundary detector has something to find
        hush(0.05)
        for w in text.split():
            tone(0.16 / rate, f0 * (1.0 + 0.04 * (len(w) % 4)))
            hush((0.34 if w.rstrip('"\')')[-1:] in ".!?" else 0.05) / rate)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(bytes(frames))
        return buf.getvalue()
