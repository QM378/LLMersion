"""Configuration for the conversation module.

Everything is an environment variable, like the rest of the project. The module
is designed to run in one of two places without changing a line:

    beside the reader   `python -m talk.main`  on its own port, borrowing the
                        reader's voice and scorer over localhost HTTP so no
                        model is loaded twice
    inside the reader   `app.include_router(talk.api.router)` — one line, later
"""
from __future__ import annotations

import os

from server import config as rc  # the reader's config: data dirs, Ollama URL

# ---------------------------------------------------------------- serving
HOST = os.environ.get("PR_TALK_HOST", rc.HOST)
PORT = int(os.environ.get("PR_TALK_PORT", "8849"))

# Where the reader is. When it answers, we use its already-resident Kokoro and
# wav2vec2 instead of loading our own copies — the whole point of the split.
READER_URL = os.environ.get("PR_READER_URL", f"http://127.0.0.1:{rc.PORT}")

# ---------------------------------------------------------------- speech in
# auto | faster-whisper | transformers | openai-whisper | dev
STT_BACKEND = os.environ.get("PR_STT", "auto")
# Size, not a full path: base.en is ~145 MB and enough for a learner reading
# aloud. small.en is noticeably better on accented speech and ~3x the cost.
STT_MODEL = os.environ.get("PR_STT_MODEL", "base.en")
STT_DIR = rc.MODELS_DIR / "stt"
STT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- dialogue
# Defaults to whatever the reader already talks to, so nothing new is pulled.
LLM_MODEL = os.environ.get("PR_TALK_MODEL", os.environ.get("PR_LLM_MODEL", "gemma3:4b"))
OLLAMA_URL = rc.OLLAMA_URL
LEVEL = os.environ.get("PR_TALK_LEVEL", "B1")        # CEFR band the tutor aims at
TURNS_KEPT = int(os.environ.get("PR_TALK_TURNS", "8"))   # history sent to the model
PASSAGE_WORDS = int(os.environ.get("PR_TALK_PASSAGE", "700"))
TARGET_WORDS = int(os.environ.get("PR_TALK_WORDS", "12"))

# ---------------------------------------------------------------- scoring
SCORE_DEFAULT = os.environ.get("PR_TALK_SCORE", "1") != "0"

# ---------------------------------------------------------------- correction
# A second, dedicated pass over what the learner said. It runs at the same time
# as the tutor's reply rather than after it, so the cost is the slower of the
# two and not their sum. Set to 0 if your machine serialises Ollama requests
# and you would rather have the latency back.
COACH = os.environ.get("PR_TALK_COACH", "1") != "0"

# Re-transcribe the growing buffer while the learner is still speaking, so they
# can see their own words appear. Cheap on a GPU, noticeable on a laptop CPU.
INTERIM = os.environ.get("PR_TALK_INTERIM", "1") != "0"

# ---------------------------------------------------------------- dev
# Fake STT and a canned tutor, so the window can be tested with no models and
# no Ollama running. Same idea as the reader's dev TTS engine.
DEV = os.environ.get("PR_TALK_DEV", "0") == "1"

DB_PATH = rc.DATA / "talk.db"
AUDIO_DIR = rc.AUDIO_DIR


def hf_name(model: str) -> str:
    """`base.en` -> `openai/whisper-base.en` for the transformers backend."""
    return model if "/" in model else f"openai/whisper-{model}"
