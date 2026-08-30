"""Translation backend registry — same shape as the TTS one."""
from __future__ import annotations

import importlib
import pkgutil
import threading
from pathlib import Path

from .base import MTBackend

REGISTRY: dict[str, type[MTBackend]] = {}


def register(cls: type[MTBackend]) -> type[MTBackend]:
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
        except Exception as exc:  # noqa: BLE001
            print(f"[mt] backend {mod.name} failed to import: {exc}")


class MTManager:
    def __init__(self) -> None:
        self._live: dict[str, MTBackend] = {}
        self._checks: dict[str, tuple[bool, str]] = {}
        self._lock = threading.RLock()

    def check(self, bid: str) -> tuple[bool, str]:
        if bid not in self._checks:
            try:
                self._checks[bid] = REGISTRY[bid].check()
            except Exception as exc:  # noqa: BLE001
                self._checks[bid] = (False, str(exc))
        return self._checks[bid]

    def refresh(self) -> None:
        self._checks.clear()

    def status(self) -> list[dict]:
        discover()
        out = []
        for cls in sorted(REGISTRY.values(), key=lambda c: (c.rank, c.id)):
            ok, why = self.check(cls.id)
            out.append({"id": cls.id, "label": cls.label, "available": ok,
                        "reason": why, "notes": cls.notes,
                        "models": cls.list_models() if ok else []})
        return out

    def default(self) -> tuple[str, str]:
        from .. import config
        discover()
        want = config.MT_BACKEND
        order = sorted(REGISTRY.values(), key=lambda c: (c.rank, c.id))
        if want != "auto":
            order = [c for c in order if c.id == want] or order
        for cls in order:
            ok, _ = self.check(cls.id)
            if not ok:
                continue
            models = cls.list_models()
            if not models:
                continue
            pref = next((m for m in models if m["id"] == config.MT_MODEL), None)
            return cls.id, (pref or models[0])["id"]
        return "none", ""

    def instance(self, bid: str) -> MTBackend:
        # anyone may call this directly (scripts, the bench harness) without
        # having listed backends first, so discovery cannot be someone else's job
        discover()
        with self._lock:
            if bid not in self._live:
                ok, why = self.check(bid)
                if not ok:
                    raise RuntimeError(f"{bid} unavailable: {why}")
                b = REGISTRY[bid]()
                b.load()
                self._live[bid] = b
            return self._live[bid]

    def translate(self, texts: list[str], backend: str, model: str) -> list[str]:
        b = self.instance(backend)
        if b.parallel <= 1 or len(texts) < 2:
            # a single local model on one GPU: serialise
            with self._lock:
                return b.translate(texts, model)
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(b.parallel, len(texts))) as ex:
            return list(ex.map(lambda t: b.translate([t], model)[0], texts))


MANAGER = MTManager()
