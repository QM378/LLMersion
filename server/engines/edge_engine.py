"""Microsoft Edge neural voices. Not open weights, but zero setup and very
natural — useful as a reference point when judging the local engines."""
from __future__ import annotations

import asyncio
import importlib.util

from . import register
from .base import TTSEngine, Voice

_VOICES = [
    ("en-US-AndrewNeural", "Andrew · General American", "male"),
    ("en-US-BrianNeural", "Brian · General American", "male"),
    ("en-US-GuyNeural", "Guy · General American", "male"),
    ("en-US-AvaNeural", "Ava · General American", "female"),
    ("en-US-EmmaNeural", "Emma · General American", "female"),
    ("en-GB-RyanNeural", "Ryan · British", "male"),
    ("en-GB-SoniaNeural", "Sonia · British", "female"),
    ("en-AU-WilliamNeural", "William · Australian", "male"),
]


@register
class EdgeEngine(TTSEngine):
    id = "edge"
    label = "Edge neural (online)"
    ext = "mp3"
    needs_network = True
    supports_speed = True
    rank = 40
    notes = "pip install edge-tts — sends the sentence to Microsoft"

    @classmethod
    def check(cls) -> tuple[bool, str]:
        if importlib.util.find_spec("edge_tts") is None:
            return False, "missing edge_tts"
        return True, ""

    @classmethod
    def list_voices(cls) -> list[Voice]:
        return [Voice(id=v, label=lab, engine=cls.id, gender=g,
                      accent=lab.split("·")[-1].strip())
                for v, lab, g in _VOICES]

    def synth(self, text: str, voice: Voice, speed: float) -> bytes:
        import edge_tts
        rate = f"{int(round((speed - 1.0) * 100)):+d}%"

        async def run() -> bytes:
            out = bytearray()
            async for chunk in edge_tts.Communicate(text, voice.id, rate=rate).stream():
                if chunk["type"] == "audio":
                    out.extend(chunk["data"])
            return bytes(out)

        return asyncio.run(run())
