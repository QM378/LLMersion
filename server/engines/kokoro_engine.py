"""Kokoro-82M — Apache-2.0, the fast baseline. General American / RP only."""
from __future__ import annotations

import importlib.util
import io

from . import register
from .base import TTSEngine, Voice

_US = [("af_heart", "Heart", "female"), ("af_bella", "Bella", "female"),
       ("af_nicole", "Nicole", "female"), ("af_sarah", "Sarah", "female"),
       ("am_michael", "Michael", "male"), ("am_fenrir", "Fenrir", "male"),
       ("am_puck", "Puck", "male"), ("am_adam", "Adam", "male")]
_UK = [("bf_emma", "Emma", "female"), ("bf_isabella", "Isabella", "female"),
       ("bm_george", "George", "male"), ("bm_lewis", "Lewis", "male")]


@register
class KokoroEngine(TTSEngine):
    id = "kokoro"
    label = "Kokoro 82M"
    ext = "wav"
    supports_speed = True
    rank = 10
    notes = "pip install kokoro soundfile  (+ torch)"

    @classmethod
    def check(cls) -> tuple[bool, str]:
        for m in ("kokoro", "soundfile", "torch"):
            if importlib.util.find_spec(m) is None:
                return False, f"missing {m}"
        return True, ""

    @classmethod
    def list_voices(cls) -> list[Voice]:
        out = []
        for vid, name, gender in _US:
            out.append(Voice(id=vid, label=f"{name} · General American",
                             engine=cls.id, accent="General American", gender=gender))
        for vid, name, gender in _UK:
            out.append(Voice(id=vid, label=f"{name} · British", engine=cls.id,
                             accent="British RP", gender=gender))
        return out

    def load(self) -> None:
        from .. import config
        self.device = config.resolve_device()
        self._pipes: dict[str, object] = {}
        self.sr = 24000
        self._fell_back = False

    def _pipe(self, lang: str):
        if lang not in self._pipes:
            from kokoro import KPipeline
            self._pipes[lang] = KPipeline(lang_code=lang, device=self.device)
        return self._pipes[lang]

    def _run(self, lang: str, text: str, voice_id: str, speed: float):
        """Some Metal kernels Kokoro needs are missing or wrong on certain
        macOS/PyTorch combinations. Rather than fail, drop to CPU once and stay
        there — an 82M model is fast enough there anyway."""
        try:
            return list(self._pipe(lang)(text, voice=voice_id, speed=speed))
        except Exception as exc:  # noqa: BLE001
            if self.device == "cpu" or self._fell_back:
                raise
            print(f"[kokoro] {self.device} failed ({exc}); falling back to CPU")
            self._fell_back = True
            self.device = "cpu"
            self._pipes.clear()
            return list(self._pipe(lang)(text, voice=voice_id, speed=speed))

    def synth(self, text: str, voice: Voice, speed: float) -> bytes:
        import numpy as np
        import soundfile as sf
        lang = "b" if voice.id.startswith("b") else "a"
        chunks = []
        for _g, _p, audio in self._run(lang, text, voice.id, speed):
            if audio is None:
                continue
            arr = audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio)
            chunks.append(arr.astype("float32").reshape(-1))
        if not chunks:
            return b""
        buf = io.BytesIO()
        sf.write(buf, np.concatenate(chunks), self.sr, format="WAV", subtype="PCM_16")
        return buf.getvalue()

    def unload(self) -> None:
        self._pipes.clear()
        try:
            import torch
            torch.cuda.empty_cache()
        except Exception:
            pass
