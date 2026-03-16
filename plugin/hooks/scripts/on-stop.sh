#!/usr/bin/env bash
# Stop Hook — clean up daemon PIDs when Claude session ends.
#
# Only kills daemons for workspaces that are in done/stopped state.
# Active experiment monitors are left alive for Sentinel to manage.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/lib/sibyl-hook-utils.sh"

WORKSPACES_DIR="$SIBYL_ROOT/workspaces"
[ -d "$WORKSPACES_DIR" ] || exit 0

for ws_dir in "$WORKSPACES_DIR"/*/; do
    [ -d "$ws_dir" ] || continue
    STATUS_FILE="${ws_dir}status.json"
    [ -f "$STATUS_FILE" ] || continue

    STAGE=$(jq -r '.stage // ""' "$STATUS_FILE" 2>/dev/null)
    STOP_REQUESTED=$(jq -r '.stop_requested // false' "$STATUS_FILE" 2>/dev/null)

    # Only clean up daemons for done/stopped projects
    if [[ "$STAGE" == "done" || "$STOP_REQUESTED" == "true" ]]; then
        WORKSPACE=$(cd "$ws_dir" && pwd)
        SCOPE=$(sibyl_scope_id "$WORKSPACE")

        # Kill self-heal monitor
        SELF_HEAL_PID="/tmp/sibyl_${SCOPE}_self_heal.pid"
        if [ -f "$SELF_HEAL_PID" ]; then
            PID=$(cat "$SELF_HEAL_PID" 2>/dev/null)
            [ -n "$PID" ] && kill "$PID" 2>/dev/null
            rm -f "$SELF_HEAL_PID"
        fi

        # Kill experiment monitor (only for stopped/done)
        EXP_MONITOR_PID="/tmp/sibyl_${SCOPE}_monitor.pid"
        if [ -f "$EXP_MONITOR_PID" ]; then
            PID=$(cat "$EXP_MONITOR_PID" 2>/dev/null)
            [ -n "$PID" ] && kill "$PID" 2>/dev/null
            rm -f "$EXP_MONITOR_PID"
        fi
    fi
done

exit 0
