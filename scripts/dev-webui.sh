#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="$ROOT_DIR/.venv/bin/python3"
API_HOST="127.0.0.1"
API_PORT="7654"
WEB_HOST="127.0.0.1"
WEB_PORT="3000"
KEEP_AUTH_KEY="0"

usage() {
  cat <<'EOF'
Usage: ./scripts/dev-webui.sh [--with-auth]

Starts the Sibyl WebUI backend and Next.js frontend together for local development.

Defaults:
  Backend API:  http://127.0.0.1:7654
  Frontend UI:  http://127.0.0.1:3000

Options:
  --with-auth   Keep SIBYL_DASHBOARD_KEY instead of unsetting it for local dev
  -h, --help    Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-auth)
      KEEP_AUTH_KEY="1"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Missing repo virtualenv interpreter: $PYTHON_BIN" >&2
  echo "Create it with: python3 -m venv .venv && .venv/bin/pip install -e ." >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required to run the WebUI frontend." >&2
  exit 1
fi

API_PID=""
WEB_PID=""

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM

  for pid in "$API_PID" "$WEB_PID"; do
    if [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" >/dev/null 2>&1 || true
    fi
  done

  wait ${API_PID:-} ${WEB_PID:-} 2>/dev/null || true
  exit "$exit_code"
}

trap cleanup EXIT INT TERM

echo "[webui-dev] Backend:  http://${API_HOST}:${API_PORT}"
echo "[webui-dev] Frontend: http://${WEB_HOST}:${WEB_PORT}"
echo "[webui-dev] Press Ctrl+C to stop both processes."

(
  cd "$ROOT_DIR"
  if [[ "$KEEP_AUTH_KEY" == "1" ]]; then
    exec "$PYTHON_BIN" -m sibyl.cli webui --host "$API_HOST" --port "$API_PORT"
  else
    exec env -u SIBYL_DASHBOARD_KEY "$PYTHON_BIN" -m sibyl.cli webui --host "$API_HOST" --port "$API_PORT"
  fi
) &
API_PID=$!

(
  cd "$ROOT_DIR/webui"
  exec npm run dev -- --hostname "$WEB_HOST" --port "$WEB_PORT"
) &
WEB_PID=$!

while true; do
  if ! kill -0 "$API_PID" >/dev/null 2>&1; then
    wait "$API_PID"
    exit $?
  fi
  if ! kill -0 "$WEB_PID" >/dev/null 2>&1; then
    wait "$WEB_PID"
    exit $?
  fi
  sleep 1
done
