#!/bin/bash
# WebSim launcher (macOS). Double-click this file.
set -euo pipefail
cd "$(dirname "$0")"

on_error() {
  echo
  echo "WebSim stopped with an error. The message above explains why."
  echo "Full log: $PWD/.websim/logs/websim.log"
  echo
  read -n 1 -s -r -p "Press any key to close this window..."
  echo
}
trap on_error ERR

export PATH="$HOME/.local/bin:$PATH"

if ! command -v uv >/dev/null 2>&1; then
  echo "WebSim: installing uv (one-time, no admin password needed)…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

echo "WebSim: preparing dependencies (first run downloads Python and packages)…"
uv sync

echo "WebSim: starting…"
uv run websim "$@"
