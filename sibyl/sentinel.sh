#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# Sibyl Sentinel - Watchdog for Claude Code experiment resilience
# ═══════════════════════════════════════════════════════════════
#
# Runs in a sibling tmux pane, monitors experiment state and
# Claude Code process health. Automatically revives Claude when
# it stops unexpectedly while experiments are still active.
#
# Usage:
#   bash sibyl/sentinel.sh <workspace_path> <tmux_pane> [poll_interval_sec]
#
# Arguments:
#   workspace_path    e.g. workspaces/ttt-dlm (relative or absolute)
#   tmux_pane         e.g. sibyl:0.0 (target pane where Claude runs)
#   poll_interval_sec default 120 (2 minutes)
#
# Stop: echo '{"stop":true}' > <workspace>/sentinel_stop.json
# ═══════════════════════════════════════════════════════════════

set -euo pipefail

SIBYL_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORKSPACE="${1:?Usage: sentinel.sh <workspace_path> <tmux_pane> [interval_sec]}"
TMUX_PANE="${2:?Usage: sentinel.sh <workspace_path> <tmux_pane> [interval_sec]}"
POLL_INTERVAL="${3:-120}"
PYTHON="$SIBYL_ROOT/.venv/bin/python3"

# Resolve workspace to absolute path
if [[ ! "$WORKSPACE" = /* ]]; then
    WORKSPACE="$SIBYL_ROOT/$WORKSPACE"
fi

HEARTBEAT_FILE="$WORKSPACE/sentinel_heartbeat.json"
SESSION_FILE="$WORKSPACE/sentinel_session.json"
STOP_FILE="$WORKSPACE/sentinel_stop.json"
STALE_THRESHOLD=300  # 5 minutes

# Consecutive wake attempts before backing off
MAX_WAKE_ATTEMPTS=3
wake_attempts=0

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] SENTINEL: $*"
}

# ─── Process detection ────────────────────────────────────────

# Get the PID of the shell running in the target tmux pane
get_pane_shell_pid() {
    tmux display-message -t "$TMUX_PANE" -p '#{pane_pid}' 2>/dev/null || echo ""
}

# Check if Claude process is running in the target tmux pane
claude_is_running() {
    local pane_pid
    pane_pid=$(get_pane_shell_pid)
    [[ -n "$pane_pid" ]] || return 1
    pgrep -P "$pane_pid" -f "claude" >/dev/null 2>&1
}

# Check if Claude has active child processes (bash commands, sleep, ssh, etc.)
# This prevents false "idle" detection when Claude is running a tool like
# `bash sleep 600` during experiment_wait polling.
claude_has_active_children() {
    local pane_pid claude_pid
    pane_pid=$(get_pane_shell_pid)
    [[ -n "$pane_pid" ]] || return 1

    # Find claude's PID (direct child of pane shell)
    claude_pid=$(pgrep -P "$pane_pid" -f "claude" 2>/dev/null | head -1)
    [[ -n "$claude_pid" ]] || return 1

    # Check if claude has any child processes (tool execution in progress)
    # Common children: bash, sleep, ssh, python3, node
    local children
    children=$(pgrep -P "$claude_pid" 2>/dev/null | wc -l | tr -d ' ')
    [[ "$children" -gt 0 ]]
}

# ─── State checks (pure file reads, no LLM) ──────────────────

# Check if experiments are active or project has ongoing work
experiments_active() {
    local config_output
    config_output=$("$PYTHON" -c "
from sibyl.orchestrate import cli_sentinel_config
cli_sentinel_config('$WORKSPACE')
" 2>/dev/null) || return 1

    local has_running stage paused
    has_running=$(echo "$config_output" | jq -r '.has_running_experiments')
    stage=$(echo "$config_output" | jq -r '.stage')
    paused=$(echo "$config_output" | jq -r '.paused')

    # Active if has running experiments
    if [[ "$has_running" == "true" ]]; then
        return 0
    fi

    # Active if stage is ongoing and not paused/done/init
    if [[ "$paused" == "false" ]] && \
       [[ "$stage" != "done" ]] && \
       [[ "$stage" != "init" ]] && \
       [[ "$stage" != "" ]]; then
        return 0
    fi

    return 1
}

# Check if heartbeat is stale (older than STALE_THRESHOLD seconds)
heartbeat_stale() {
    if [[ ! -f "$HEARTBEAT_FILE" ]]; then
        return 0  # No heartbeat file = stale
    fi
    local ts now diff
    ts=$(jq -r '.ts' "$HEARTBEAT_FILE" 2>/dev/null) || return 0
    now=$(date +%s)
    # Handle float timestamps (truncate to int)
    diff=$((now - ${ts%%.*}))
    [[ $diff -gt $STALE_THRESHOLD ]]
}

# Get saved session ID for --resume
get_session_id() {
    if [[ -f "$SESSION_FILE" ]]; then
        jq -r '.session_id // ""' "$SESSION_FILE" 2>/dev/null || echo ""
    else
        echo ""
    fi
}

# ─── Actions ──────────────────────────────────────────────────

# Restart Claude Code in the target pane (Case A: process dead)
restart_claude() {
    local session_id
    session_id=$(get_session_id)

    log "RESTART: Claude process not found, restarting..."

    if [[ -n "$session_id" ]]; then
        log "  Resuming session: ${session_id:0:12}..."
        tmux send-keys -t "$TMUX_PANE" "cd $SIBYL_ROOT && claude --resume $session_id" Enter
    else
        log "  No session ID, using --continue"
        tmux send-keys -t "$TMUX_PANE" "cd $SIBYL_ROOT && claude --continue" Enter
    fi

    # Wait for Claude to start (up to 90 seconds)
    local waited=0
    while ! claude_is_running && [[ $waited -lt 90 ]]; do
        sleep 5
        waited=$((waited + 5))
        log "  Waiting for Claude to start... (${waited}s)"
    done

    if claude_is_running; then
        log "  Claude started. Waiting 15s for initialization..."
        sleep 15
        # Inject resume command
        local project_name
        project_name=$(basename "$WORKSPACE")
        tmux send-keys -t "$TMUX_PANE" "/sibyl-research:continue $project_name" Enter
        log "  Injected /sibyl-research:continue $project_name"
        wake_attempts=0
    else
        log "  ERROR: Claude failed to start after 90s"
        wake_attempts=$((wake_attempts + 1))
    fi
}

# Wake up an idle Claude session (Case B: process alive but stale heartbeat)
wake_claude() {
    log "WAKE: Heartbeat stale, nudging Claude..."
    local project_name
    project_name=$(basename "$WORKSPACE")
    tmux send-keys -t "$TMUX_PANE" "/sibyl-research:continue $project_name" Enter
    log "  Injected /sibyl-research:continue $project_name"
    wake_attempts=$((wake_attempts + 1))
}

# ═══════════════════════════════════════════════════════════════
# Main loop
# ═══════════════════════════════════════════════════════════════

log "╔═══════════════════════════════════════╗"
log "║   SIBYL SENTINEL - Watchdog Active    ║"
log "╚═══════════════════════════════════════╝"
log "  Workspace:  $WORKSPACE"
log "  Target:     $TMUX_PANE"
log "  Interval:   ${POLL_INTERVAL}s"
log "  Stale:      ${STALE_THRESHOLD}s"
log ""

while true; do
    # ── Check stop signal ──
    if [[ -f "$STOP_FILE" ]]; then
        log "Stop signal received. Goodbye."
        rm -f "$STOP_FILE"
        exit 0
    fi

    # ── Check if project is active ──
    if ! experiments_active; then
        log "idle - no active work"
        wake_attempts=0
        sleep "$POLL_INTERVAL"
        continue
    fi

    # ── Back-off: too many consecutive wake attempts ──
    if [[ $wake_attempts -ge $MAX_WAKE_ATTEMPTS ]]; then
        local backoff=$((POLL_INTERVAL * 3))
        log "BACKOFF: $wake_attempts consecutive attempts failed, sleeping ${backoff}s"
        sleep "$backoff"
        wake_attempts=0
        continue
    fi

    # ── Case A: Claude process is dead ──
    if ! claude_is_running; then
        log "Claude NOT running! Confirming in 5s..."
        sleep 5
        if ! claude_is_running; then
            restart_claude
            sleep "$POLL_INTERVAL"
            continue
        fi
    fi

    # ── Claude is running ──

    # Check for active children (bash/sleep/ssh tool execution)
    if claude_has_active_children; then
        log "ok - Claude running, tool executing (has children)"
        wake_attempts=0
        sleep "$POLL_INTERVAL"
        continue
    fi

    # No active children - check heartbeat freshness
    if heartbeat_stale; then
        log "Claude running but heartbeat stale, no active tools"
        wake_claude
    else
        log "ok - Claude running, heartbeat fresh"
        wake_attempts=0
    fi

    sleep "$POLL_INTERVAL"
done
