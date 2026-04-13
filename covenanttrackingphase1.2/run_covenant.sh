#!/usr/bin/env bash
set -euo pipefail

# Automated runner for covenanttrackingphase1.
# Usage examples:
#   ./run_covenant.sh web
#   ./run_covenant.sh web --port 8002
#   ./run_covenant.sh deterministic --file /absolute/path/to/input.xlsx
#   ./run_covenant.sh agentic --file /absolute/path/to/input.xlsx
#   ./run_covenant.sh web --skip-sync

MODE="${1:-web}"
if [[ $# -gt 0 ]]; then
  shift
fi

HOST="${COVENANT_WEB_HOST:-127.0.0.1}"
PORT="${COVENANT_WEB_PORT:-8000}"
FILE_PATH=""
SKIP_SYNC="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      HOST="${2:-}"
      shift 2
      ;;
    --port)
      PORT="${2:-}"
      shift 2
      ;;
    --file)
      FILE_PATH="${2:-}"
      shift 2
      ;;
    --skip-sync)
      SKIP_SYNC="1"
      shift
      ;;
    -h|--help)
      cat <<'EOF'
Automated runner for covenanttrackingphase1

Usage:
  ./run_covenant.sh [mode] [options]

Modes:
  web            Start web upload app (default)
  deterministic  Run deterministic pipeline from CLI
  agentic        Run CrewAI agent mode from CLI

Options:
  --file <path>   Excel file path for deterministic/agentic modes
  --host <host>   Host for web mode (default: 127.0.0.1)
  --port <port>   Port for web mode (default: 8000)
  --skip-sync     Skip 'uv sync' step
  -h, --help      Show this help
EOF
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if ! command -v uv >/dev/null 2>&1; then
  echo "Error: 'uv' is not installed. Install it first: pip install uv" >&2
  exit 1
fi

if [[ "$SKIP_SYNC" != "1" ]]; then
  echo "==> Syncing environment with uv..."
  UV_NO_EDITABLE=1 uv sync
fi

case "$MODE" in
  web)
    echo "==> Starting web app at http://${HOST}:${PORT}"
    export COVENANT_WEB_HOST="$HOST"
    export COVENANT_WEB_PORT="$PORT"
    exec uv run covenant_web
    ;;
  deterministic)
    echo "==> Running deterministic pipeline..."
    if [[ -n "$FILE_PATH" ]]; then
      exec uv run covenanttrackingphase1 "$FILE_PATH"
    fi
    exec uv run covenanttrackingphase1
    ;;
  agentic)
    echo "==> Running agentic CLI pipeline..."
    if [[ -n "$FILE_PATH" ]]; then
      exec env COVENANT_USE_AGENTS=1 uv run covenanttrackingphase1 "$FILE_PATH"
    fi
    exec env COVENANT_USE_AGENTS=1 uv run covenanttrackingphase1
    ;;
  *)
    echo "Error: invalid mode '$MODE'. Use: web | deterministic | agentic" >&2
    exit 1
    ;;
esac
