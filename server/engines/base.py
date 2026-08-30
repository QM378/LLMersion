"""Contracts every TTS engine implements.

An engine is a file in this package that subclasses `TTSEngine` and carries the
`@register` decorator. Nothing else in the codebase needs to know it exists —
discovery, listing, loading, unloading, caching and the UI dropdown all follow
from the class attributes below.

A *voice* is either **builtin** (shipped with the engine, e.g. Kokoro's
`am_michael`) or a **clone pack**: a folder under `models/voices/` holding a
reference recording. Any engine with `supports_cloning = True` can speak with
any clone pack, which is how regional accents get in — you cannot download a
"Chicago male" checkpoint, but you can hand a cloning model six seconds of one.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .. import config

REF_SUFFIXES = (".wav", ".flac", ".mp3", ".ogg", ".m4a")


@dataclass
class Voice:
    id: str                       # unique within its engine
    label: str                    # what the dropdown shows
    engine: str
    kind: str = "builtin"         # builtin | clone
    accent: str = ""              # free text: "New York", "General American"
    gender: str = ""              # male | female | ""
    ref: str = ""                 # clone packs: path to the reference audio
    ref_text: str = ""            # transcript of the reference, some engines want it
    params: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.engine}|{self.id}"

    def as_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "engine": self.engine,
                "kind": self.kind, "accent": self.accent, "gender": self.gender,
                "key": self.key}


def _read_meta(folder: Path) -> dict:
    for name in ("voice.json", "voice.toml"):
        p = folder / name
        if not p.exists():
            continue
        if name.endswith(".json"):
            return json.loads(p.read_text(encoding="utf-8"))
        try:
            import tomllib
            return tomllib.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def clone_packs() -> list[dict]:
    """Scan models/voices/ for reference recordings.

    A pack is a folder containing one audio file. `voice.json`/`voice.toml` is
    optional metadata:

        label   = "Carl — Queens, NY"
        accent  = "New York"
        gender  = "male"
        engines = ["chatterbox"]      # omit to offer it to every cloning engine
        ref_text = "..."              # transcript, needed by some engines
        [params]
        exaggeration = 0.45
    """
    out: list[dict] = []
    root = config.VOICES_DIR
    if not root.exists():
        return out
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        audio = next((f for f in sorted(folder.iterdir())
                      if f.suffix.lower() in REF_SUFFIXES), None)
        if audio is None:
            continue
        meta = _read_meta(folder)
        out.append({
            "id": folder.name,
            "label": meta.get("label") or folder.name.replace("_", " "),
            "accent": meta.get("accent", ""),
            "gender": meta.get("gender", ""),
            "engines": meta.get("engines") or [],
            "ref": str(audio),
            "ref_text": meta.get("ref_text", ""),
            "params": meta.get("params", {}),
        })
    return out


def clone_voices_for(engine_id: str) -> list[Voice]:
    return [
        Voice(id="clone:" + p["id"], label=p["label"], engine=engine_id, kind="clone",
              accent=p["accent"], gender=p["gender"], ref=p["ref"],
              ref_text=p["ref_text"], params=p["params"])
        for p in clone_packs()
        if not p["engines"] or engine_id in p["engines"]
    ]


class TTSEngine:
    """Subclass, set the attributes, implement `list_voices` and `synth`."""

    id: str = ""
    label: str = ""
    ext: str = "wav"              # container the bytes are in
    supports_cloning: bool = False
    supports_speed: bool = True   # False -> the client applies playbackRate instead
    needs_network: bool = False
    notes: str = ""               # shown in the UI when the engine is unavailable
    rank: int = 100               # lower is preferred when auto-selecting

    # -- discovery ---------------------------------------------------------
    @classmethod
    def check(cls) -> tuple[bool, str]:
        """Can this engine run here? Must be cheap — no model loading."""
        return True, ""

    @classmethod
    def list_voices(cls) -> list[Voice]:
        return []

    # -- lifecycle ---------------------------------------------------------
    def load(self) -> None:
        """Bring weights into memory. Called lazily on first synth."""

    def unload(self) -> None:
        """Release VRAM. Called when another engine needs the space."""

    # -- work --------------------------------------------------------------
    def synth(self, text: str, voice: Voice, speed: float) -> bytes:
        raise NotImplementedError
