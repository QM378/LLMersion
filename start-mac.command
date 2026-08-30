#!/usr/bin/env bash
# LLMersion-1 — macOS / Linux launcher.
# ./start-mac.command dev  uses the no-model test voice.
set -e
cd "$(dirname "$0")"

if [ -d .venv ]; then
  source .venv/bin/activate
elif command -v conda >/dev/null 2>&1; then
  # shellcheck disable=SC1091
  source "$(conda info --base)/etc/profile.d/conda.sh"
  conda activate reader
else
  echo "No .venv and no conda. Run ./setup-mac.command first."
  exit 1
fi

[ "${1:-}" = "dev" ] && export PR_DEV=1
exec python -m server.main
