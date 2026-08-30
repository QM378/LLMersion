"""macOS `say` / pyttsx3. Robotic, but always there."""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import register
from .base import TTSEngine, Voice


@register
class SystemEngine(TTSEngine):
    id = "system"
    label = "System voice"
    ext = "wav"
    rank = 90
    notes = "macOS `say`, or pip install pyttsx3 elsewhere"

    @classmethod
    def check(cls) -> tuple[bool, str]:
        if shutil.which("say") or importlib.util.find_spec("pyttsx3"):
            return True, ""
        return False, "no `say` binary and no pyttsx3"

    @classmethod
    def list_voices(cls) -> list[Voice]:
        if shutil.which("say"):
            names = []
            try:
                out = subprocess.run(["say", "-v", "?"], capture_output=True,
                                     text=True, timeout=5).stdout
                for line in out.splitlines():
                    if "en_US" in line or "en_GB" in line:
                        names.append(line.split()[0])
            except Exception:
                names = ["Alex", "Samantha"]
            return [Voice(id=n, label=n, engine=cls.id) for n in names[:20]]
        return [Voice(id="default", label="System default", engine=cls.id)]

    def load(self) -> None:
        self.say = shutil.which("say")
        self.engine = None
        if not self.say:
            import pyttsx3
            self.engine = pyttsx3.init()

    def synth(self, text: str, voice: Voice, speed: float) -> bytes:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "a.wav"
            if self.say:
                subprocess.run([self.say, "-v", voice.id, "-r", str(int(190 * speed)),
                                "-o", str(out), "--data-format=LEI16@22050", text], check=True)
            else:
                self.engine.setProperty("rate", int(190 * speed))
                self.engine.save_to_file(text, str(out))
                self.engine.runAndWait()
            return out.read_bytes()
