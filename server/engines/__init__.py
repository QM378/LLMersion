"""Engine registry: drop a file in this folder and it shows up in the UI."""
from __future__ import annotations

import importlib
import pkgutil
import threading
from collections import OrderedDict
from pathlib import Path

from .. import config
from .base import TTSEngine, Voice, clone_packs  # noqa: F401  (re-exported)

REGISTRY: dict[str, type[TTSEngine]] = {}


def register(cls: type[TTSEngine]) -> type[TTSEngine]:
    if not cls.id:
        raise ValueError(f"{cls.__name__} needs an id")
    REGISTRY[cls.id] = cls
    return cls


_discovered = False


def discover() -> None:
    global _discovered
    if _discovered:
        return
    _discovered = True
    for mod in pkgutil.iter_modules([str(Path(__file__).parent)]):
        if mod.name.startswith("_") or mod.name == "base":
            continue
        try:
            importlib.import_module(f"{__name__}.{mod.name}")
        except Exception as exc:  # noqa: BLE001 — a broken engine must not kill the app
            print(f"[tts] engine module {mod.name} failed to import: {exc}")


class Manager:
    """Lazily loads engines and keeps at most PR_TTS_KEEP of them resident."""

    def __init__(self) -> None:
        self._live: OrderedDict[str, TTSEngine] = OrderedDict()
        self._lock = threading.RLock()
        self._checks: dict[str, tuple[bool, str]] = {}

    # -- introspection -----------------------------------------------------
    def check(self, engine_id: str) -> tuple[bool, str]:
        if engine_id not in self._checks:
            cls = REGISTRY[engine_id]
            try:
                self._checks[engine_id] = cls.check()
            except Exception as exc:  # noqa: BLE001
                self._checks[engine_id] = (False, str(exc))
        return self._checks[engine_id]

    def status(self) -> list[dict]:
        discover()
        out = []
        for cls in sorted(REGISTRY.values(), key=lambda c: (c.rank, c.id)):
            ok, why = self.check(cls.id)
            n = len(cls.list_voices()) if ok else 0
            out.append({
                "id": cls.id, "label": cls.label, "available": ok, "reason": why,
                "cloning": cls.supports_cloning, "speed": cls.supports_speed,
                "network": cls.needs_network, "notes": cls.notes,
                "voices": n, "loaded": cls.id in self._live,
            })
        return out

    def voices(self) -> list[Voice]:
        discover()
        out: list[Voice] = []
        for cls in sorted(REGISTRY.values(), key=lambda c: (c.rank, c.id)):
            ok, _ = self.check(cls.id)
            if not ok:
                continue
            try:
                out.extend(cls.list_voices())
            except Exception as exc:  # noqa: BLE001
                print(f"[tts] {cls.id}.list_voices failed: {exc}")
        return out

    def default_voice(self) -> Voice | None:
        wanted_engine = config.TTS_ENGINE
        wanted_voice = config.TTS_VOICE
        vs = self.voices()
        if not vs:
            return None
        if wanted_voice:
            hit = next((v for v in vs if v.id == wanted_voice
                        and (wanted_engine in ("auto", v.engine))), None)
            if hit:
                return hit
        if wanted_engine != "auto":
            hit = next((v for v in vs if v.engine == wanted_engine), None)
            if hit:
                return hit
        return vs[0]

    def find(self, engine_id: str, voice_id: str) -> Voice:
        for v in self.voices():
            if v.engine == engine_id and v.id == voice_id:
                return v
        raise KeyError(f"unknown voice {engine_id}|{voice_id}")

    # -- lifecycle ---------------------------------------------------------
    def instance(self, engine_id: str) -> TTSEngine:
        with self._lock:
            if engine_id in self._live:
                self._live.move_to_end(engine_id)
                return self._live[engine_id]
            ok, why = self.check(engine_id)
            if not ok:
                raise RuntimeError(f"{engine_id} unavailable: {why}")
            eng = REGISTRY[engine_id]()
            eng.load()
            self._live[engine_id] = eng
            while len(self._live) > max(1, config.TTS_KEEP):
                old_id, old = self._live.popitem(last=False)
                print(f"[tts] unloading {old_id} to make room")
                try:
                    old.unload()
                except Exception:  # noqa: BLE001
                    pass
            return eng

    def unload_all(self) -> None:
        with self._lock:
            for eid, eng in list(self._live.items()):
                try:
                    eng.unload()
                except Exception:  # noqa: BLE001
                    pass
                self._live.pop(eid, None)

    # -- work --------------------------------------------------------------
    def synth(self, text: str, voice: Voice, speed: float) -> bytes:
        eng = self.instance(voice.engine)
        with self._lock:                    # one model, one GPU, one call at a time
            return eng.synth(text, voice, speed)


MANAGER = Manager()
