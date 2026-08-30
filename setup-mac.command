#!/usr/bin/env bash
# LLMersion-1 — one-time setup for macOS and Linux.
# Finds conda (or falls back to venv), builds the environment, installs the
# right PyTorch for this machine, then the reader and its default models.
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '  %s\n' "$*"; }
die() { printf '\n  %s\n\n' "$*" >&2; exit 1; }

echo
say "LLMersion-1 setup"
say "------------------------------------------------------------"

[ -f server/main.py ] || die "Wrong folder: $PWD has no server/main.py"

OS="$(uname -s)"
case "$OS" in
  Darwin) PLATFORM="macOS $(uname -m)" ;;
  Linux)  PLATFORM="Linux $(uname -m)" ;;
  *)      PLATFORM="$OS" ;;
esac
say "platform   $PLATFORM"

# ---------------------------------------------------------------- conda?
if command -v conda >/dev/null 2>&1; then
  say "conda      found"
  # shellcheck disable=SC1091
  source "$(conda info --base)/etc/profile.d/conda.sh"
  if conda env list | awk '{print $1}' | grep -qx reader; then
    say "environment \"reader\" already exists"
  else
    say "creating environment \"reader\" with Python 3.12 ..."
    conda create -n reader python=3.12 -y >/dev/null
  fi
  conda activate reader
else
  say "conda      not found, using a local .venv instead"
  command -v python3 >/dev/null 2>&1 || die "No python3 either. Install Python 3.12 first."
  [ -d .venv ] || python3 -m venv .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

python -m pip install --upgrade pip --quiet

# ---------------------------------------------------------------- torch
echo
if [ "$OS" = "Darwin" ]; then
  if [ "$(uname -m)" = "arm64" ]; then
    say "GPU        Apple silicon — installing PyTorch with Metal (MPS)"
  else
    say "GPU        Intel Mac — installing CPU PyTorch"
  fi
  pip install torch --quiet
elif command -v nvidia-smi >/dev/null 2>&1; then
  IDX=cu128
  nvidia-smi | grep -q "CUDA Version: 13" && IDX=cu130
  say "GPU        NVIDIA detected — installing PyTorch $IDX (~2 GB)"
  pip install torch --index-url "https://download.pytorch.org/whl/$IDX"
else
  say "GPU        none detected — installing CPU PyTorch"
  say "           Kokoro still works, roughly 1-3x realtime"
  pip install torch --quiet
fi

# ---------------------------------------------------------------- the app
echo
say "installing the reader ..."
pip install -r requirements/core.txt --quiet
say "installing Kokoro (the voice) ..."
pip install -r requirements/voice.txt --quiet
say "installing the small translation model and pronunciation scoring ..."
pip install -r requirements/translate.txt --quiet
# optional: ~5x faster sentence splitting, no arm64 macOS wheel exists
pip install blingfire --quiet 2>/dev/null || say "blingfire unavailable — using the built-in splitter"

# Kokoro's grapheme-to-phoneme falls back to espeak for words it does not know
if [ "$OS" = "Darwin" ] && ! command -v espeak-ng >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    say "installing espeak-ng (needed for unusual words) ..."
    brew install espeak-ng >/dev/null 2>&1 || say "espeak-ng install failed — usually still fine"
  else
    say "note: install Homebrew then 'brew install espeak-ng' if odd words mispronounce"
  fi
fi

# ---------------------------------------------------------------- check
echo
say "------------------------------------------------------------"
python - <<'EOF'
import torch
if torch.cuda.is_available():
    dev = "cuda"
elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
    dev = "mps"
else:
    dev = "cpu"
print(f"  torch      {torch.__version__} on {dev}")
x = torch.randn(512, 512, device=dev)
float((x @ x).sum())
print("  kernel     ok")
EOF
python -c "import fitz, fastapi, soundfile; print('  reader     ok')"
python -c "import kokoro; print('  kokoro     ok')"
python -c "import transformers; print('  translate  ok (opus-mt, downloads on first use)')"
say "------------------------------------------------------------"
echo
say "Done. Run ./start-mac.command to launch it."
say "For better Chinese, see docs/INSTALL.md for Ollama."
echo
