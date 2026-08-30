"""Chatterbox (Resemble AI) — MIT weights, zero-shot voice cloning.

This is the engine that gives you regional accents. There is no downloadable
"Chicago male" checkpoint anywhere; what exists is a model that will imitate any
6-20 second reference clip, so a clip of a Chicago speaker *is* the voice.
Drop reference audio in <data-dir>/models/voices/<name>/ and it appears in
the dropdown. See docs/voices.md.
"""
from __future__ import annotations

import importlib.util
import io

from . import register
from .base import TTSEngine, Voice, clone_voices_for


@register
class ChatterboxEngine(TTSEngine):
    id = "chatterbox"
    label = "Chatterbox (clone)"
    ext = "wav"
    supports_cloning = True
    supports_speed = False          # no rate knob; the client resamples instead
    rank = 20
    notes = "pip install chatterbox-tts  (+ torch). Needs a clip in <data>/models/voices/"

    @classmethod
    def check(cls) -> tuple[bool, str]:
        for m in ("chatterbox", "torch", "soundfile"):
            if importlib.util.find_spec(m) is None:
                return False, f"missing {m}"
        return True, ""

    @classmethod
    def list_voices(cls) -> list[Voice]:
        base = [Voice(id="default", label="Chatterbox default", engine=cls.id,
                      accent="General American")]
        return base + clone_voices_for(cls.id)

    def load(self) -> None:
        from chatterbox.tts import ChatterboxTTS
        from .. import config
        dev = config.resolve_device()
        self.model = ChatterboxTTS.from_pretrained(device=dev)

    def synth(self, text: str, voice: Voice, speed: float) -> bytes:
        import soundfile as sf
        p = voice.params or {}
        kw = {
            "exaggeration": float(p.get("exaggeration", 0.5)),
            "cfg_weight": float(p.get("cfg", 0.5)),
        }
        if voice.ref:
            kw["audio_prompt_path"] = voice.ref
        wav = self.model.generate(text, **kw)
        arr = wav.squeeze(0).detach().cpu().numpy() if hasattr(wav, "squeeze") else wav
        buf = io.BytesIO()
        sf.write(buf, arr, self.model.sr, format="WAV", subtype="PCM_16")
        return buf.getvalue()

    def unload(self) -> None:
        self.model = None
        try:
            import torch
            torch.cuda.empty_cache()
        except Exception:
            pass
