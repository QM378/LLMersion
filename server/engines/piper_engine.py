"""Piper — ONNX, tiny, CPU-friendly. Voices are .onnx files in a folder.

This is the "a folder of models" case: drop any piper voice into
<data-dir>/models/tts/piper/ and it appears in the dropdown after a refresh.
"""
from __future__ import annotations

import importlib.util
import io
import wave

from . import register
from .base import TTSEngine, Voice


@register
class PiperEngine(TTSEngine):
    id = "piper"
    label = "Piper (ONNX)"
    ext = "wav"
    supports_speed = True
    rank = 30
    notes = "pip install piper-tts, then put .onnx voices in <data>/models/tts/piper/"

    @classmethod
    def check(cls) -> tuple[bool, str]:
        if importlib.util.find_spec("piper") is None:
            return False, "missing piper"
        from .. import config
        if not list(config.PIPER_DIR.glob("**/*.onnx")):
            return False, f"no .onnx voices in {config.PIPER_DIR}"
        return True, ""

    @classmethod
    def list_voices(cls) -> list[Voice]:
        from .. import config
        out = []
        for p in sorted(config.PIPER_DIR.glob("**/*.onnx")):
            stem = p.stem
            gender = "male" if "-male" in stem or stem.endswith("_m") else ""
            out.append(Voice(id=stem, label=stem.replace("_", " "), engine=cls.id,
                             gender=gender, params={"path": str(p)}))
        return out

    def load(self) -> None:
        self._voices: dict[str, object] = {}

    def _voice(self, v: Voice):
        if v.id not in self._voices:
            from piper.voice import PiperVoice
            self._voices[v.id] = PiperVoice.load(v.params["path"])
        return self._voices[v.id]

    def synth(self, text: str, voice: Voice, speed: float) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            self._voice(voice).synthesize(text, w, length_scale=1.0 / max(0.1, speed))
        return buf.getvalue()

    def unload(self) -> None:
        self._voices.clear()
