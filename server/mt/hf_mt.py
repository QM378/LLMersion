"""Dedicated MT models from HuggingFace — small, fast, no LLM needed."""
from __future__ import annotations

import importlib.util

from . import register
from .base import MTBackend

MODELS = [
    {"id": "Helsinki-NLP/opus-mt-en-zh", "label": "opus-mt en-zh (77M, very fast)"},
    {"id": "facebook/nllb-200-distilled-600M", "label": "NLLB-200 600M"},
    {"id": "facebook/nllb-200-1.3B", "label": "NLLB-200 1.3B"},
    {"id": "google/madlad400-3b-mt", "label": "MADLAD-400 3B"},
]


@register
class HFBackend(MTBackend):
    id = "hf"
    label = "HuggingFace MT"
    rank = 20
    notes = "pip install transformers sentencepiece sacremoses"

    @classmethod
    def check(cls) -> tuple[bool, str]:
        for m in ("transformers", "torch", "sentencepiece"):
            if importlib.util.find_spec(m) is None:
                return False, f"missing {m}"
        return True, ""

    @classmethod
    def list_models(cls) -> list[dict]:
        return MODELS

    def load(self) -> None:
        self._cache: dict[str, tuple] = {}

    def _pair(self, model: str):
        if model not in self._cache:
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
            from .. import config
            dev = config.resolve_device()
            tok = AutoTokenizer.from_pretrained(model)
            mdl = AutoModelForSeq2SeqLM.from_pretrained(model).to(dev).eval()
            # Marian configs ship a default max_length; clearing it lets
            # max_new_tokens govern alone instead of warning on every call
            mdl.generation_config.max_length = None
            self._cache = {model: (tok, mdl, dev)}   # keep only the current one
        return self._cache[model]

    def translate(self, texts: list[str], model: str) -> list[str]:
        import torch
        from ..textseg import split_sentences
        tok, mdl, dev = self._pair(model)
        kw = {}
        if "nllb" in model:
            kw["forced_bos_token_id"] = tok.convert_tokens_to_ids("zho_Hans")
        out = []
        for t in texts:
            src = [s["text"] for s in split_sentences(t)] or [t]
            if "madlad" in model:
                src = ["<2zh> " + s for s in src]
            batch = tok(src, return_tensors="pt", padding=True,
                        truncation=True, max_length=512).to(dev)
            with torch.inference_mode():
                gen = mdl.generate(**batch, max_new_tokens=512, num_beams=4, **kw)
            out.append("".join(tok.batch_decode(gen, skip_special_tokens=True)))
        return out
