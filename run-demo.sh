#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"

if [ ! -f "$BACKEND_DIR/.env" ]; then
  echo "Missing backend/.env"
  echo "Copy backend/.env.example to backend/.env and add FIREWORKS_API_KEY first."
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "The uv Python package manager is required: https://docs.astral.sh/uv/"
  exit 1
fi

cleanup() {
  kill "${MCP_PID:-}" "${API_PID:-}" "${UI_PID:-}" "${OLLAMA_PID:-}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if command -v ollama >/dev/null 2>&1 && ! curl --max-time 1 -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  ollama serve >/tmp/gridspec-ollama.log 2>&1 &
  OLLAMA_PID=$!
  for _ in {1..20}; do
    if curl --max-time 1 -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
      break
    fi
    sleep 0.25
  done
fi

cd "$BACKEND_DIR"
uv sync
uv run python -m catalog_mcp.server &
MCP_PID=$!
uv run python run_api.py &
API_PID=$!

cd "$PROJECT_DIR"
if [ ! -d node_modules ]; then
  npm install
fi
npm run dev &
UI_PID=$!

echo "GridSpec is starting:"
echo "  React UI:   http://localhost:3000"
echo "  Python API: http://127.0.0.1:8000/docs"
echo "  MCP server: http://127.0.0.1:8001/mcp"
if curl --max-time 1 -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  echo "  Candidate model: Ollama (local)"
else
  echo "  Candidate model: Fireworks fallback (Ollama is not running)"
fi
echo "Press Ctrl+C to stop all services."

wait "$UI_PID"
