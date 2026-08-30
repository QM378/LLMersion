"""Contract for translation backends."""
from __future__ import annotations


class MTBackend:
    id: str = ""
    label: str = ""
    rank: int = 100
    notes: str = ""
    parallel: int = 1      # >1 means the backend is safe to call concurrently

    @classmethod
    def check(cls) -> tuple[bool, str]:
        return True, ""

    @classmethod
    def list_models(cls) -> list[dict]:
        """[{id, label}] — populates the model dropdown."""
        return []

    def load(self) -> None:
        pass

    def translate(self, texts: list[str], model: str) -> list[str]:
        raise NotImplementedError


SYS_PROMPT = (
    "You are a professional English-to-Chinese translator for academic and technical prose. "
    "Translate the user's text into fluent, faithful Simplified Chinese. "
    "Keep inline math, code identifiers, citation markers and proper nouns intact. "
    "Output ONLY the translation, with no preface, no quotes, no explanation."
)
