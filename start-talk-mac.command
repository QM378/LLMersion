#!/bin/bash
# Document conversation, beside the reader. Pass "dev" for the no-model demo.
cd "$(dirname "$0")"
[ -f .venv/bin/activate ] && source .venv/bin/activate
python -m talk.main "$1"
