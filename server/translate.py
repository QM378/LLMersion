"""Cached translation in front of the backend registry."""
from __future__ import annotations

from . import cache
from .mt import MANAGER


def info() -> dict:
    bid, model = MANAGER.default()
    return {"backends": MANAGER.status(), "default": {"backend": bid, "model": model}}


def translate(texts: list[str], backend: str = "", model: str = "") -> list[str]:
    if not backend or not model:
        d_backend, d_model = MANAGER.default()
        backend = backend or d_backend
        model = model or d_model
    if backend == "none" or not model:
        return ["" for _ in texts]

    tag = f"{backend}:{model}"
    keys = [cache.sha1(tag, t) for t in texts]
    results: list[str | None] = [cache.get_trans(k) for k in keys]

    todo = [i for i, r in enumerate(results) if r is None]
    if todo:
        fresh = MANAGER.translate([texts[i] for i in todo], backend, model)
        for i, zh in zip(todo, fresh):
            results[i] = zh
            if zh:
                cache.put_trans(keys[i], zh)
    return [r or "" for r in results]
