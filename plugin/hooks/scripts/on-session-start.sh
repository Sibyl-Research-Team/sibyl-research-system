#!/usr/bin/env bash
# SessionStart Hook — initialize background monitors on session start/resume.
#
# Responsibilities:
#   1. Start self-heal monitor daemon for active workspaces
#   2. Detect pending lark sync and write trigger context
#   3. Restart experiment monitor daemons that died during session gap
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/lib/sibyl-hook-utils.sh"

# Read hook input (SessionStart provides session_id, cwd, etc.)
INPUT=$(sibyl_read_hook_input)
CWD=$(echo "$INPUT" | jq -r '.cwd // ""' 2>/dev/null)

# Find workspaces directory
WORKSPACES_DIR="$SIBYL_ROOT/workspaces"
[ -d "$WORKSPACES_DIR" ] || exit 0

RECOVERY_NOTES=""

for ws_dir in "$WORKSPACES_DIR"/*/; do
    [ -d "$ws_dir" ] || continue
    STATUS_FILE="${ws_dir}status.json"
    [ -f "$STATUS_FILE" ] || continue

    # Read workspace stage
    STAGE=$(jq -r '.stage // ""' "$STATUS_FILE" 2>/dev/null)
    STOP_REQUESTED=$(jq -r '.stop_requested // false' "$STATUS_FILE" 2>/dev/null)

    # Skip inactive workspaces
    [[ "$STAGE" == "done" || "$STAGE" == "init" || "$STAGE" == "" ]] && continue
    [[ "$STOP_REQUESTED" == "true" ]] && continue

    WORKSPACE=$(cd "$ws_dir" && pwd)
    SCOPE=$(sibyl_scope_id "$WORKSPACE")

    # ── 1. Self-heal monitor daemon ──
    SELF_HEAL_ENABLED=$("$SIBYL_PYTHON" -c "
import yaml, sys
try:
    cfg = yaml.safe_load(open(sys.argv[1]))
    print(str(cfg.get('self_heal_enabled', True)).lower())
except Exception:
    print('true')
" "${ws_dir}config.yaml" 2>/dev/null || echo "true")
    SELF_HEAL_PID="/tmp/sibyl_${SCOPE}_self_heal.pid"
    if [[ "$SELF_HEAL_ENABLED" != "false" ]] && ! sibyl_pid_alive "$SELF_HEAL_PID"; then
        INTERVAL=$("$SIBYL_PYTHON" -c "
import yaml, sys
try:
    cfg = yaml.safe_load(open(sys.argv[1]))
    print(cfg.get('self_heal_interval_sec', 300))
except Exception:
    print(300)
" "${ws_dir}config.yaml" 2>/dev/null || echo "300")
        # Launch inline self-heal monitor loop
        nohup bash -c "
            while true; do
                cd '$SIBYL_ROOT' && '$SIBYL_PYTHON' -m sibyl.cli self-heal-scan '$WORKSPACE' > /dev/null 2>&1
                sleep $INTERVAL
            done
        " > "/tmp/sibyl_${SCOPE}_self_heal.log" 2>&1 &
        echo $! > "$SELF_HEAL_PID"
        RECOVERY_NOTES="${RECOVERY_NOTES}Self-heal monitor started for $(basename "$WORKSPACE"). "
    fi

    # ── 2. Pending lark sync check ──
    PENDING_SYNC="${WORKSPACE}/lark_sync/pending_sync.jsonl"
    SYNC_STATUS="${WORKSPACE}/lark_sync/sync_status.json"
    if [ -f "$PENDING_SYNC" ]; then
        PENDING_LINES=$(wc -l < "$PENDING_SYNC" 2>/dev/null | tr -d ' ')
        SYNCED_LINES=0
        if [ -f "$SYNC_STATUS" ]; then
            SYNCED_LINES=$(jq -r '.last_synced_line // 0' "$SYNC_STATUS" 2>/dev/null || echo "0")
        fi
        if [ "$PENDING_LINES" -gt "$SYNCED_LINES" ] 2>/dev/null; then
            RECOVERY_NOTES="${RECOVERY_NOTES}Pending lark sync for $(basename "$WORKSPACE") ($((PENDING_LINES - SYNCED_LINES)) entries). "
        fi
    fi

    # ── 3. Dead experiment monitor recovery ──
    EXP_MONITOR_PID="/tmp/sibyl_${SCOPE}_monitor.pid"
    EXP_MONITOR_SCRIPT="/tmp/sibyl_${SCOPE}_monitor_daemon.sh"
    if [ -f "$EXP_MONITOR_SCRIPT" ] && ! sibyl_pid_alive "$EXP_MONITOR_PID"; then
        # Check if there are running experiments
        EXP_STATE="${WORKSPACE}/current/exp/experiment_state.json"
        [ -f "$EXP_STATE" ] || EXP_STATE="${WORKSPACE}/exp/experiment_state.json"
        HAS_RUNNING=false
        if [ -f "$EXP_STATE" ]; then
            RUNNING_COUNT=$(jq '[.tasks // {} | to_entries[] | select(.value.status == "running")] | length' "$EXP_STATE" 2>/dev/null || echo "0")
            [ "$RUNNING_COUNT" -gt 0 ] && HAS_RUNNING=true
        fi

        if [ "$HAS_RUNNING" = "true" ]; then
            LOG_FILE="/tmp/sibyl_${SCOPE}_monitor.log"
            nohup bash "$EXP_MONITOR_SCRIPT" > "$LOG_FILE" 2>&1 &
            echo $! > "$EXP_MONITOR_PID"
            RECOVERY_NOTES="${RECOVERY_NOTES}Experiment monitor daemon restarted for $(basename "$WORKSPACE"). "
        fi
    fi
done

# Output recovery notes as system message if any
if [ -n "$RECOVERY_NOTES" ]; then
    printf '{"systemMessage":"[SIBYL-SESSION-HOOK] %s"}\n' \
        "$(echo "$RECOVERY_NOTES" | sed 's/"/\\"/g')"
fi

exit 0
