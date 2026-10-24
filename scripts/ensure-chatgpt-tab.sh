#!/bin/bash
# Start the isolated GPT Bridge Chrome. It never reads or controls personal Chrome tabs.
set -e
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
PYTHON="${GPT_BRIDGE_PYTHON:-$ROOT/.venv/bin/python}"
if [ ! -x "$PYTHON" ]; then PYTHON=python3; fi
exec "$PYTHON" -m chatgpt_api.dedicated_browser start --account second "$@"
