"""Runtime configuration. Everything is overridable by environment variables."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _user_data_dir() -> Path:
    """Per-user state directory, following each platform's convention.

    State lives outside the project on purpose: replacing the code should never
    cost you the audio cache, the translations, the vocabulary or your place in
    a document.
    """
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / "ReadingDesk"


DATA = Path(os.environ["PR_DATA"]) if os.environ.get("PR_DATA") else _user_data_dir()

DOCS_DIR = DATA / "docs"
AUDIO_DIR = DATA / "audio"
DB_PATH = DATA / "reader.db"
DICT_DB = Path(os.environ.get("PR_DICT_DB", DATA / "ecdict.db"))

MODELS_DIR = Path(os.environ.get("PR_MODELS", DATA / "models"))
VOICES_DIR = Path(os.environ.get("PR_VOICES", MODELS_DIR / "voices"))
PIPER_DIR = Path(os.environ.get("PR_PIPER_DIR", MODELS_DIR / "tts" / "piper"))

for _p in (DATA, DOCS_DIR, AUDIO_DIR, VOICES_DIR, PIPER_DIR):
    _p.mkdir(parents=True, exist_ok=True)

HOST = os.environ.get("PR_HOST", "127.0.0.1")
PORT = int(os.environ.get("PR_PORT", "8848"))
# Set PR_TOKEN when binding to anything other than loopback. Requests must then
# carry ?token=... or an X-Reader-Token header. This is a doorstop, not
# security — put it behind SSH or a reverse proxy for anything real.
TOKEN = os.environ.get("PR_TOKEN", "")


def is_local() -> bool:
    return HOST in ("127.0.0.1", "localhost", "::1")

# ---------------------------------------------------------------- TTS
# auto, or any engine id registered in server/engines/
TTS_ENGINE = os.environ.get("PR_TTS", "auto")
TTS_VOICE = os.environ.get("PR_TTS_VOICE", "")   # empty -> first voice available
TTS_SPEED = float(os.environ.get("PR_TTS_SPEED", "1.0"))
TTS_KEEP = int(os.environ.get("PR_TTS_KEEP", "1"))   # engines kept resident in VRAM
# paragraph = one pass per paragraph (natural prosody); sentence = one pass per sentence
TTS_UNIT = os.environ.get("PR_TTS_UNIT", "paragraph")

# ---------------------------------------------------------------- translate
# auto, or any backend id registered in server/mt/
MT_BACKEND = os.environ.get("PR_MT", "auto")
MT_MODEL = os.environ.get("PR_MT_MODEL", "")   # preferred model, if it is installed
OLLAMA_URL = os.environ.get("PR_OLLAMA_URL", "http://127.0.0.1:11434")

# ---------------------------------------------------------------- pronunciation
# a phoneme-level CTC model; the learner's audio and the TTS reference both go
# through it, so no grapheme-to-phoneme component is needed
ASR_MODEL = os.environ.get("PR_ASR_MODEL", "facebook/wav2vec2-lv-60-espeak-cv-ft")

DEVICE = os.environ.get("PR_DEVICE", "auto")  # auto | cuda | mps | cpu


def resolve_device() -> str:
    if DEVICE != "auto":
        return DEVICE
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"
