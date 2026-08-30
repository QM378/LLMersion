"""Any instruct model served by Ollama. Model choice is a UI dropdown."""
from __future__ import annotations

from . import register
from .base import MTBackend, SYS_PROMPT


@register
class OllamaBackend(MTBackend):
    id = "ollama"
    label = "Ollama (local LLM)"
    rank = 10
    # ollama serves several requests at once; a paragraph at a time in parallel
    # beats a serial batch by roughly the same factor
    parallel = 4
    notes = "install ollama, then `ollama pull <model>`"

    @classmethod
    def _tags(cls) -> list[str]:
        import requests
        from .. import config
        r = requests.get(f"{config.OLLAMA_URL}/api/tags", timeout=3)
        r.raise_for_status()
        return sorted(m["name"] for m in r.json().get("models", []))

    @classmethod
    def check(cls) -> tuple[bool, str]:
        try:
            names = cls._tags()
        except Exception as exc:  # noqa: BLE001
            return False, f"ollama not reachable ({type(exc).__name__})"
        if not names:
            return False, "ollama has no models pulled"
        return True, ""

    @classmethod
    def list_models(cls) -> list[dict]:
        try:
            return [{"id": n, "label": n} for n in cls._tags()]
        except Exception:  # noqa: BLE001
            return []

    def translate(self, texts: list[str], model: str) -> list[str]:
        import requests
        from .. import config
        out = []
        for t in texts:
            r = requests.post(
                f"{config.OLLAMA_URL}/api/chat",
                json={"model": model, "stream": False,
                      "options": {"temperature": 0.2, "num_ctx": 2048,
                                  "num_predict": 1024},
                      "messages": [{"role": "system", "content": SYS_PROMPT},
                                   {"role": "user", "content": t}]},
                timeout=180)
            r.raise_for_status()
            msg = r.json().get("message", {}).get("content", "").strip()
            if "</think>" in msg:
                msg = msg.split("</think>")[-1].strip()
            out.append(msg)
        return out
