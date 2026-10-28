#!/usr/bin/env bash
# macOS/Linux port of dashboard.ps1: creates .venv if missing, installs
# dependencies, checks ffmpeg/ffprobe, builds web/ if stale, then serves the
# FastAPI dashboard (API + built SPA) with uvicorn.
#
# Usage:
#   ./dashboard.sh                    # localhost only, port 8766, opens browser
#   ./dashboard.sh --port 9000 --no-browser
#   ./dashboard.sh --lan              # bind 0.0.0.0 (reachable from your LAN)
set -euo pipefail

PORT=8766
OPEN_BROWSER=1
HOST=127.0.0.1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --no-browser) OPEN_BROWSER=0; shift ;;
    --lan) HOST=0.0.0.0; shift ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"
# Finder/.app launches get a minimal PATH; add Homebrew + Node 24.
export PATH="/opt/homebrew/opt/node@24/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

URL="http://localhost:$PORT"
open_browser() { [[ $OPEN_BROWSER == 1 ]] && open "$URL" || true; }

# Port in use? Reuse it if it is our dashboard, else fail clearly.
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  if curl -fsS --max-time 3 "$URL/api/health" 2>/dev/null | grep -q '"whisper_models"'; then
    echo "A podcast-autopilot dashboard is already running on port $PORT -- reusing it."
    open_browser; exit 0
  fi
  echo "Port $PORT is in use by another process. Run './dashboard.sh --port <other>'." >&2
  exit 1
fi

VENV_PY="$REPO_ROOT/.venv/bin/python"
REQ_STAMP="$REPO_ROOT/.venv/.requirements.sha"
if [[ ! -x "$VENV_PY" ]]; then
  BOOT_PY="$(command -v python3.12 || command -v python3)"
  echo "Creating virtual environment with $BOOT_PY ..."
  "$BOOT_PY" -m venv "$REPO_ROOT/.venv"
fi

# Only reinstall when requirements/pyproject change (keeps launches fast).
REQ_SHA="$(cat requirements.txt pyproject.toml | shasum | cut -d' ' -f1)"
if [[ ! -f "$REQ_STAMP" || "$(cat "$REQ_STAMP")" != "$REQ_SHA" ]]; then
  echo "Installing Python dependencies (first run can take a few minutes) ..."
  "$VENV_PY" -m pip install --quiet --upgrade pip
  "$VENV_PY" -m pip install --quiet -r requirements.txt
  "$VENV_PY" -m pip install --quiet -e .
  echo "$REQ_SHA" > "$REQ_STAMP"
fi

echo "Checking ffmpeg/ffprobe ..."
if ! "$VENV_PY" -c "from podcast_autopilot.config import resolve_ffmpeg_binaries; f,p=resolve_ffmpeg_binaries(); print('ffmpeg:',f); print('ffprobe:',p)"; then
  echo "ffmpeg/ffprobe not found. Install with: brew install ffmpeg" >&2
  exit 1
fi

if [[ -f web/package.json ]]; then
  newest_src="$(find web/src web/index.html web/package.json -type f -newer web/dist/index.html 2>/dev/null | head -1 || true)"
  if [[ ! -f web/dist/index.html || -n "$newest_src" ]]; then
    command -v npm >/dev/null || { echo "npm not found (need Node; brew install node@24)." >&2; exit 1; }
    echo "Building web/ frontend ..."
    (cd web && { [[ -d node_modules ]] || npm ci; } && npm run build)
  else
    echo "web/dist is up to date, skipping build."
  fi
fi

"$VENV_PY" -m podcast_autopilot make-example --out-dir examples >/dev/null

echo "Dashboard: $URL"
if [[ $HOST == 0.0.0.0 ]]; then
  LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || true)"
  [[ -n "$LAN_IP" ]] && echo "LAN:       http://$LAN_IP:$PORT"
fi
echo "Keep this window open. Use Quit in the dashboard (or Ctrl-C) to stop."

# Open the browser once the server answers.
( for _ in $(seq 1 60); do
    curl -fsS --max-time 1 "$URL/api/health" >/dev/null 2>&1 && { open_browser; exit 0; }
    sleep 0.5
  done ) &

exec "$VENV_PY" -m uvicorn "podcast_autopilot.server:create_app" --factory --host "$HOST" --port "$PORT"
