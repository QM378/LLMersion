"""Copy this to `myengine_engine.py`, fill it in, restart. That is the whole
process for adding a text-to-speech model — no other file changes.

The class attributes drive everything:

  supports_cloning  -> the engine is offered every clone pack in models/voices/
  supports_speed    -> False means the server ignores `speed` and the browser
                       applies playbackRate instead (better cache reuse, at the
                       cost of a small pitch shift)
  rank              -> lower wins when the app picks a default
  check()           -> must be cheap; never import the heavy model here
  notes             -> shown in the UI when check() fails, so say how to install

Concrete examples worth copying from:
  kokoro_engine.py      builtin voice list, per-language pipelines
  piper_engine.py       voices discovered by globbing a model folder
  chatterbox_engine.py  zero-shot cloning from a reference clip
"""
from __future__ import annotations

import importlib.util
import io

from . import register
from .base import TTSEngine, Voice, clone_voices_for


# @register            <- uncomment to switch it on
class MyEngine(TTSEngine):
    id = "myengine"
    label = "My Engine"
    ext = "wav"                    # or "mp3"
    supports_cloning = False
    supports_speed = True
    rank = 50
    notes = "pip install my-engine"

    @classmethod
    def check(cls) -> tuple[bool, str]:
        if importlib.util.find_spec("my_engine") is None:
            return False, "missing my_engine"
        return True, ""

    @classmethod
    def list_voices(cls) -> list[Voice]:
        voices = [Voice(id="narrator", label="Narrator", engine=cls.id,
                        accent="General American", gender="male")]
        if cls.supports_cloning:
            voices += clone_voices_for(cls.id)
        return voices

    def load(self) -> None:
        from .. import config
        import my_engine
        self.model = my_engine.load(device=config.resolve_device())

    def synth(self, text: str, voice: Voice, speed: float) -> bytes:
        import soundfile as sf
        audio, sr = self.model.tts(text, speaker=voice.id, speed=speed)
        buf = io.BytesIO()
        sf.write(buf, audio, sr, format="WAV", subtype="PCM_16")
        return buf.getvalue()

    def unload(self) -> None:
        self.model = None
