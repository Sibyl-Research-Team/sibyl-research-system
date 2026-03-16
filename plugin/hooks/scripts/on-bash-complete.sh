#!/usr/bin/env bash
# PostToolUse(Bash) Hook — routes sibyl CLI results to background triggers.
#
# Fires after every Bash tool call. Quick-exits if not a sibyl CLI call.
# Two routes:
#   1. cli_record returned sync_requested:true → inject lark sync context
#   2. cli_next returned experiment_monitor.script → launch bash monitor daemon
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/lib/sibyl-hook-utils.sh"

INPUT=$(sibyl_read_hook_input)

# Quick exit: only process sibyl CLI calls
COMMAND=$(sibyl_hook_tool_command "$INPUT")
[[ "$COMMAND" == *"sibyl.cli"* ]] || exit 0

RESPONSE=$(sibyl_hook_tool_response "$INPUT")
[ -n "$RESPONSE" ] || exit 0

# ── Route 1: Lark Sync Trigger ──────────────────────────────────────────────
# Detect cli_record output with sync_requested: true
if echo "$RESPONSE" | grep -q '"sync_requested"' 2>/dev/null; then
    SYNC_REQUESTED=$(echo "$RESPONSE" | jq -r '.sync_requested // false' 2>/dev/null)
    if [ "$SYNC_REQUESTED" = "true" ]; then
        WORKSPACE=$(sibyl_extract_workspace "$COMMAND")
        if [ -n "$WORKSPACE" ]; then
            # Resolve to absolute path
            if [[ "$WORKSPACE" != /* ]]; then
                WORKSPACE="$SIBYL_ROOT/$WORKSPACE"
            fi

            # Check lock file — skip if sync already in progress
            LOCK_FILE="$WORKSPACE/lark_sync/sync.lock"
            if [ -f "$LOCK_FILE" ]; then
                LOCK_MTIME=$(stat -f %m "$LOCK_FILE" 2>/dev/null || stat -c %Y "$LOCK_FILE" 2>/dev/null || echo 0)
                LOCK_AGE=$(( $(date +%s) - LOCK_MTIME ))
                if [ "$LOCK_AGE" -lt 600 ]; then
                    # Sync in progress (lock < 10min old), skip
                    exit 0
                fi
            fi

            # Try deterministic sync first (zero LLM tokens)
            PYTHON_EXE="$SIBYL_ROOT/.venv/bin/python3"
            if [ -x "$PYTHON_EXE" ]; then
                SYNC_RESULT=$(cd "$SIBYL_ROOT" && "$PYTHON_EXE" -m sibyl.cli lark-sync "$WORKSPACE" 2>/dev/null)
                SYNC_STATUS=$(echo "$SYNC_RESULT" | jq -r '.status // "error"' 2>/dev/null)
                if [ "$SYNC_STATUS" = "ok" ]; then
                    # Deterministic sync succeeded — zero token cost
                    exit 0
                fi
            fi

            # Fallback: inject context for LLM agent sync
            sibyl_inject_context "[LARK-SYNC-HOOK] sync_requested=true detected for $WORKSPACE. Deterministic sync failed or unavailable. Start sibyl-lark-sync background agent: Agent tool (run_in_background=true), Skill sibyl-lark-sync, args=$WORKSPACE"
            exit 0
        fi
    fi
fi

# ── Route 2: Experiment Monitor Daemon Launch ────────────────────────────────
# Detect cli_next output with experiment_monitor containing a script
if echo "$RESPONSE" | grep -q '"experiment_monitor"' 2>/dev/null; then
    # Check if response has experiment_monitor.script
    MONITOR_SCRIPT=$(echo "$RESPONSE" | jq -r '.experiment_monitor.script // empty' 2>/dev/null)
    if [ -n "$MONITOR_SCRIPT" ]; then
        WORKSPACE=$(sibyl_extract_workspace "$COMMAND")
        if [ -n "$WORKSPACE" ]; then
            if [[ "$WORKSPACE" != /* ]]; then
                WORKSPACE="$SIBYL_ROOT/$WORKSPACE"
            fi

            SCOPE=$(sibyl_scope_id "$WORKSPACE")
            PID_FILE="/tmp/sibyl_${SCOPE}_monitor.pid"
            SCRIPT_FILE="/tmp/sibyl_${SCOPE}_monitor_daemon.sh"

            # Idempotent: skip if daemon already running
            if sibyl_pid_alive "$PID_FILE"; then
                exit 0
            fi

            # Write and launch the monitor daemon (restricted perms)
            printf '%s\n' "$MONITOR_SCRIPT" > "$SCRIPT_FILE"
            chmod 700 "$SCRIPT_FILE"
            # Validate script header
            [[ "$(head -1 "$SCRIPT_FILE")" == "#!/"* ]] || exit 0
            LOG_FILE="/tmp/sibyl_${SCOPE}_monitor.log"
            nohup bash "$SCRIPT_FILE" > "$LOG_FILE" 2>&1 &
            DAEMON_PID=$!
            echo "$DAEMON_PID" > "$PID_FILE"

            sibyl_inject_context "[EXP-MONITOR-HOOK] Experiment monitor daemon launched (PID=$DAEMON_PID). The bash daemon handles SSH polling, GPU refresh, and dispatch detection. No need to start background_agent (supervisor). Monitor marker: $(echo "$RESPONSE" | jq -r '.experiment_monitor.marker_file // ""' 2>/dev/null)"
            exit 0
        fi
    fi
fi

exit 0
