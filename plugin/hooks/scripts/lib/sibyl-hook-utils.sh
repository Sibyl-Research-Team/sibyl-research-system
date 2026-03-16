#!/usr/bin/env bash
# Sibyl Hook Utilities — shared functions for all hook scripts.
# Source this file: . "$(dirname "$0")/lib/sibyl-hook-utils.sh"

# Resolve SIBYL_ROOT from hook script location (plugin/hooks/scripts/lib/)
_HOOK_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIBYL_ROOT="$(cd "$_HOOK_LIB_DIR/../../../.." && pwd)"
SIBYL_PYTHON="$SIBYL_ROOT/.venv/bin/python3"

# Compute workspace scope ID (must match Python workspace_scope_id())
sibyl_scope_id() {
    local workspace="$1"
    local resolved
    resolved=$(cd "$workspace" 2>/dev/null && pwd) || resolved="$workspace"
    # Strip trailing /current to match Python's resolve_workspace_root()
    [[ "$resolved" == */current ]] && resolved="${resolved%/current}"
    local proj
    proj=$(basename "$resolved" | sed 's/[^a-zA-Z0-9_.-]/-/g' | sed 's/^-\|-$//g')
    [ -z "$proj" ] && proj="sibyl"
    local digest
    digest=$(printf '%s' "$resolved" | shasum -a 1 | cut -c1-10)
    echo "${proj}_${digest}"
}

# Build project-scoped marker file path under /tmp
sibyl_marker_file() {
    local workspace="$1"
    local suffix="$2"
    local scope
    scope=$(sibyl_scope_id "$workspace")
    local safe_suffix
    safe_suffix=$(echo "$suffix" | sed 's/[^a-zA-Z0-9_.-]/-/g' | sed 's/^-\|-$//g')
    [ -z "$safe_suffix" ] && safe_suffix="marker"
    echo "/tmp/sibyl_${scope}_${safe_suffix}.json"
}

# Extract workspace path from a sibyl CLI bash command string.
# Handles: python3 -m sibyl.cli record 'workspace' ...
#          python3 -m sibyl.cli record "workspace" ...
#          python3 -m sibyl.cli record workspace ...
sibyl_extract_workspace() {
    local cmd="$1"
    # Try single-quoted arg after CLI subcommand
    local ws
    ws=$(echo "$cmd" | grep -oP "sibyl\.cli\s+\S+\s+'([^']+)'" | head -1 | grep -oP "'([^']+)'" | tr -d "'") 2>/dev/null
    [ -n "$ws" ] && echo "$ws" && return
    # Try double-quoted arg
    ws=$(echo "$cmd" | grep -oP 'sibyl\.cli\s+\S+\s+"([^"]+)"' | head -1 | grep -oP '"([^"]+)"' | tr -d '"') 2>/dev/null
    [ -n "$ws" ] && echo "$ws" && return
    # Try unquoted arg (first non-flag token after subcommand)
    ws=$(echo "$cmd" | grep -oP 'sibyl\.cli\s+\S+\s+(\S+)' | head -1 | awk '{print $NF}') 2>/dev/null
    [ -n "$ws" ] && echo "$ws" && return
    echo ""
}

# Read hook input from stdin (called once, cached)
_HOOK_INPUT=""
sibyl_read_hook_input() {
    if [ -z "$_HOOK_INPUT" ]; then
        _HOOK_INPUT=$(cat)
    fi
    echo "$_HOOK_INPUT"
}

# Extract fields from hook input JSON
sibyl_hook_tool_name() {
    echo "$1" | jq -r '.tool_name // ""' 2>/dev/null
}

sibyl_hook_tool_command() {
    echo "$1" | jq -r '.tool_input.command // ""' 2>/dev/null
}

sibyl_hook_tool_response() {
    # tool_response may be string or object with stdout field
    local resp
    resp=$(echo "$1" | jq -r '
        if .tool_response | type == "object" then
            .tool_response.stdout // (.tool_response | tostring)
        elif .tool_response | type == "string" then
            .tool_response
        else
            ""
        end
    ' 2>/dev/null) || resp=""
    echo "$resp"
}

# Check if a PID file exists and the process is alive
sibyl_pid_alive() {
    local pid_file="$1"
    [ -f "$pid_file" ] || return 1
    local pid
    pid=$(cat "$pid_file" 2>/dev/null) || return 1
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

# Atomic JSON write
sibyl_write_json() {
    local path="$1"
    local content="$2"
    local tmp="${path}.tmp.$$"
    mkdir -p "$(dirname "$path")"
    printf '%s\n' "$content" > "$tmp"
    mv -f "$tmp" "$path"
}

# Output hook response with additionalContext injection
sibyl_inject_context() {
    local context="$1"
    printf '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"%s"}}\n' \
        "$(echo "$context" | sed 's/"/\\"/g' | tr '\n' ' ')"
}
