#!/usr/bin/env bash
# Manage per-project ttyd instances for Sibyl WebUI terminal access.
set -euo pipefail

PORT_BASE="${SIBYL_TTYD_PORT_BASE:-7681}"
PORT_MAX="${SIBYL_TTYD_PORT_MAX:-7699}"
STATE_DIR="${SIBYL_TTYD_STATE_DIR:-/tmp}"

mkdir -p "$STATE_DIR"

state_file() {
  local project="$1"
  printf '%s/sibyl_ttyd_%s.json' "$STATE_DIR" "$project"
}

pid_file() {
  local project="$1"
  printf '%s/sibyl_ttyd_%s.pid' "$STATE_DIR" "$project"
}

is_running() {
  local pid="$1"
  if [[ -z "$pid" ]]; then
    return 1
  fi
  kill -0 "$pid" >/dev/null 2>&1
}

find_free_port() {
  local port="$PORT_BASE"
  while [[ "$port" -le "$PORT_MAX" ]]; do
    if ! lsof -i ":$port" >/dev/null 2>&1; then
      echo "$port"
      return 0
    fi
    port=$((port + 1))
  done
  return 1
}

write_state() {
  local project="$1"
  local port="$2"
  local pid="$3"
  local tmux_target="$4"
  local started_at
  started_at="$(date +%s)"
  cat >"$(state_file "$project")" <<EOF
{"project":"$project","port":$port,"pid":$pid,"tmux_target":"$tmux_target","started_at":$started_at}
EOF
  echo "$pid" >"$(pid_file "$project")"
}

print_state() {
  local project="$1"
  if [[ -f "$(state_file "$project")" ]]; then
    cat "$(state_file "$project")"
  else
    echo "{\"project\":\"$project\",\"running\":false}"
  fi
}

case "${1:-}" in
  start)
    PROJECT="${2:?project_name required}"
    TMUX_TARGET="${3:-sibyl}"

    if [[ -f "$(pid_file "$PROJECT")" ]]; then
      EXISTING_PID="$(cat "$(pid_file "$PROJECT")" 2>/dev/null || true)"
      if is_running "$EXISTING_PID"; then
        print_state "$PROJECT"
        exit 0
      fi
      rm -f "$(pid_file "$PROJECT")" "$(state_file "$PROJECT")"
    fi

    PORT="$(find_free_port)" || {
      echo "ERROR: No free ports in range $PORT_BASE-$PORT_MAX" >&2
      exit 1
    }

    ttyd --port "$PORT" --interface 127.0.0.1 --writable \
      tmux attach-session -t "$TMUX_TARGET" >/dev/null 2>&1 &
    PID=$!

    write_state "$PROJECT" "$PORT" "$PID" "$TMUX_TARGET"
    print_state "$PROJECT"
    ;;

  stop)
    PROJECT="${2:?project_name required}"
    PID_FILE="$(pid_file "$PROJECT")"
    if [[ -f "$PID_FILE" ]]; then
      PID="$(cat "$PID_FILE" 2>/dev/null || true)"
      if is_running "$PID"; then
        kill "$PID" >/dev/null 2>&1 || true
      fi
      rm -f "$PID_FILE" "$(state_file "$PROJECT")"
      echo "{\"project\":\"$PROJECT\",\"stopped\":true}"
    else
      echo "{\"project\":\"$PROJECT\",\"stopped\":false,\"reason\":\"not_running\"}"
    fi
    ;;

  inspect)
    PROJECT="${2:?project_name required}"
    print_state "$PROJECT"
    ;;

  status)
    shopt -s nullglob
    files=("$STATE_DIR"/sibyl_ttyd_*.json)
    if [[ "${#files[@]}" -eq 0 ]]; then
      echo "[]"
      exit 0
    fi
    printf '['
    first=1
    for file in "${files[@]}"; do
      if [[ "$first" -eq 0 ]]; then
        printf ','
      fi
      first=0
      cat "$file"
    done
    printf ']\n'
    ;;

  *)
    echo "Usage: $0 start|stop|inspect|status [project] [tmux_target]" >&2
    exit 1
    ;;
esac
