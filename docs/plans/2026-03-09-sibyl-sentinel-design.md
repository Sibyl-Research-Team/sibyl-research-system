# Sibyl Sentinel Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a tmux-pane watchdog that automatically detects and revives a stopped Claude Code session when Sibyl experiments are still active.

**Architecture:** Three-layer resilience: L1 (Ralph Loop Stop hook, already exists), L2 (tmux persistent session, already exists), L3 (Sentinel watchdog bash script in a sibling tmux pane). Sentinel is a pure-bash loop that checks experiment state files and Claude process health every 2 minutes, injecting resume commands into the Claude pane when needed.

**Tech Stack:** Bash (sentinel script), Python (heartbeat in orchestrator), tmux send-keys API

---

### Task 1: Create sentinel heartbeat writer in orchestrator

**Files:**
- Modify: `sibyl/orchestrate.py` (add heartbeat helper + calls in cli_next/cli_record)

**Step 1: Write the failing test**

Create `tests/test_sentinel.py`:

```python
"""Tests for Sentinel heartbeat and session persistence."""
import json
import time
from pathlib import Path

import pytest

from sibyl.orchestrate import cli_next, cli_record, _write_sentinel_heartbeat


@pytest.fixture
def workspace(tmp_path):
    """Minimal workspace for heartbeat tests."""
    ws = tmp_path / "test_project"
    ws.mkdir()
    (ws / "status.json").write_text(json.dumps({
        "stage": "experiment_cycle",
        "started_at": time.time(),
        "updated_at": time.time(),
        "iteration": 1,
        "errors": [],
        "paused_at": 0.0,
        "iteration_dirs": False,
    }))
    (ws / "config.yaml").write_text("topic: test\nssh_server: test\nremote_base: /tmp/test\n")
    return ws


def test_write_heartbeat_creates_file(workspace):
    _write_sentinel_heartbeat(str(workspace), "experiment_cycle", "polling")
    hb_path = workspace / "sentinel_heartbeat.json"
    assert hb_path.exists()
    data = json.loads(hb_path.read_text())
    assert data["stage"] == "experiment_cycle"
    assert data["action"] == "polling"
    assert "ts" in data
    assert abs(data["ts"] - time.time()) < 5


def test_write_heartbeat_updates_timestamp(workspace):
    _write_sentinel_heartbeat(str(workspace), "literature_search", "cli_next")
    hb1 = json.loads((workspace / "sentinel_heartbeat.json").read_text())
    time.sleep(0.1)
    _write_sentinel_heartbeat(str(workspace), "planning", "cli_record")
    hb2 = json.loads((workspace / "sentinel_heartbeat.json").read_text())
    assert hb2["ts"] >= hb1["ts"]
    assert hb2["stage"] == "planning"
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 -m pytest tests/test_sentinel.py -v`
Expected: FAIL with `ImportError: cannot import name '_write_sentinel_heartbeat'`

**Step 3: Implement heartbeat writer**

Add to `sibyl/orchestrate.py` (near the CLI functions at bottom):

```python
def _write_sentinel_heartbeat(workspace_path: str, stage: str, action: str):
    """Write heartbeat file for Sentinel watchdog."""
    hb_path = Path(workspace_path) / "sentinel_heartbeat.json"
    hb_path.write_text(json.dumps({
        "ts": time.time(),
        "stage": stage,
        "action": action,
    }))
```

Then add heartbeat calls at the end of `cli_next` and `cli_record`:

In `cli_next`, after `print(json.dumps(...))`:
```python
    try:
        _write_sentinel_heartbeat(workspace_path, action.get("stage", ""), "cli_next")
    except Exception:
        pass  # Heartbeat is best-effort, never block orchestration
```

In `cli_record`, after `print(json.dumps(output))`:
```python
    try:
        _write_sentinel_heartbeat(workspace_path, stage, "cli_record")
    except Exception:
        pass
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python3 -m pytest tests/test_sentinel.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add sibyl/orchestrate.py tests/test_sentinel.py
git commit -m "feat(sentinel): add heartbeat writer to orchestrator"
```

---

### Task 2: Create session ID persistence

**Files:**
- Modify: `sibyl/orchestrate.py` (add cli_sentinel_session)

**Step 1: Write the failing test**

Append to `tests/test_sentinel.py`:

```python
from sibyl.orchestrate import cli_sentinel_session, cli_sentinel_config


def test_sentinel_session_write_and_read(workspace):
    cli_sentinel_session(str(workspace), "abc-123-def")
    session_path = workspace / "sentinel_session.json"
    assert session_path.exists()
    data = json.loads(session_path.read_text())
    assert data["session_id"] == "abc-123-def"
    assert "saved_at" in data


def test_sentinel_config_returns_status(workspace):
    # Write a session first
    cli_sentinel_session(str(workspace), "test-session")
    _write_sentinel_heartbeat(str(workspace), "experiment_cycle", "cli_next")

    # Capture stdout
    import io, sys
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    cli_sentinel_config(str(workspace))
    output = sys.stdout.getvalue()
    sys.stdout = old_stdout

    data = json.loads(output)
    assert data["session_id"] == "test-session"
    assert data["workspace_path"] == str(workspace)
    assert "heartbeat" in data
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 -m pytest tests/test_sentinel.py -v -k "session or config"`
Expected: FAIL with `ImportError`

**Step 3: Implement session persistence**

Add to `sibyl/orchestrate.py`:

```python
def cli_sentinel_session(workspace_path: str, session_id: str):
    """CLI: Save Claude Code session ID for Sentinel resume."""
    session_path = Path(workspace_path) / "sentinel_session.json"
    session_path.write_text(json.dumps({
        "session_id": session_id,
        "saved_at": time.time(),
    }))
    print(json.dumps({"status": "ok", "session_id": session_id}))


def cli_sentinel_config(workspace_path: str):
    """CLI: Get Sentinel configuration for watchdog script."""
    ws_path = Path(workspace_path)
    session_data = {}
    session_path = ws_path / "sentinel_session.json"
    if session_path.exists():
        try:
            session_data = json.loads(session_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    heartbeat = {}
    hb_path = ws_path / "sentinel_heartbeat.json"
    if hb_path.exists():
        try:
            heartbeat = json.loads(hb_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    # Check if project has running experiments
    has_running = False
    exp_state_path = ws_path / "exp" / "experiment_state.json"
    if exp_state_path.exists():
        try:
            exp_data = json.loads(exp_state_path.read_text())
            for t in exp_data.get("tasks", {}).values():
                if t.get("status") == "running":
                    has_running = True
                    break
        except (json.JSONDecodeError, OSError):
            pass

    # Also check gpu_progress running map
    gpu_progress_path = ws_path / "exp" / "gpu_progress.json"
    if not has_running and gpu_progress_path.exists():
        try:
            gp = json.loads(gpu_progress_path.read_text())
            if gp.get("running"):
                has_running = True
        except (json.JSONDecodeError, OSError):
            pass

    # Check project status stage
    status_path = ws_path / "status.json"
    stage = ""
    paused = False
    if status_path.exists():
        try:
            st = json.loads(status_path.read_text())
            stage = st.get("stage", "")
            paused = st.get("paused_at", 0) > 0
        except (json.JSONDecodeError, OSError):
            pass

    print(json.dumps({
        "workspace_path": str(ws_path),
        "session_id": session_data.get("session_id", ""),
        "heartbeat": heartbeat,
        "has_running_experiments": has_running,
        "stage": stage,
        "paused": paused,
    }, indent=2))
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python3 -m pytest tests/test_sentinel.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add sibyl/orchestrate.py tests/test_sentinel.py
git commit -m "feat(sentinel): add session ID persistence and config endpoint"
```

---

### Task 3: Create the Sentinel bash script

**Files:**
- Create: `sibyl/sentinel.sh`

**Step 1: Write the script**

```bash
#!/bin/bash
# Sibyl Sentinel - Watchdog for Claude Code experiment resilience
#
# Runs in a sibling tmux pane, monitors experiment state,
# and revives Claude Code when it stops unexpectedly.
#
# Usage: bash sibyl/sentinel.sh <workspace_path> <tmux_pane> [poll_interval_sec]
#   workspace_path: e.g. workspaces/ttt-dlm
#   tmux_pane:      e.g. sibyl:0.0
#   poll_interval_sec: default 120 (2 minutes)

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
STALE_THRESHOLD=300  # 5 minutes default

log() {
    echo "[$(date '+%H:%M:%S')] SENTINEL: $*"
}

# Check if Claude process is running in the target tmux pane
claude_is_running() {
    local pane_pid
    pane_pid=$(tmux display-message -t "$TMUX_PANE" -p '#{pane_pid}' 2>/dev/null) || return 1
    # Check if any child process of the pane shell is a claude process
    pgrep -P "$pane_pid" -f "claude" >/dev/null 2>&1
}

# Check if experiments are active (pure file check, no LLM)
experiments_active() {
    local config_output
    config_output=$("$PYTHON" -c "from sibyl.orchestrate import cli_sentinel_config; cli_sentinel_config('$WORKSPACE')" 2>/dev/null) || return 1

    local has_running stage paused
    has_running=$(echo "$config_output" | jq -r '.has_running_experiments')
    stage=$(echo "$config_output" | jq -r '.stage')
    paused=$(echo "$config_output" | jq -r '.paused')

    # Active if: has running experiments, or stage is experiment-related and not paused
    if [[ "$has_running" == "true" ]]; then
        return 0
    fi

    # Also consider active if stage suggests ongoing work and not explicitly paused/done
    if [[ "$paused" == "false" ]] && [[ "$stage" != "done" ]] && [[ "$stage" != "init" ]] && [[ -n "$stage" ]]; then
        return 0
    fi

    return 1
}

# Check if heartbeat is stale
heartbeat_stale() {
    if [[ ! -f "$HEARTBEAT_FILE" ]]; then
        return 0  # No heartbeat = stale
    fi
    local ts now diff
    ts=$(jq -r '.ts' "$HEARTBEAT_FILE" 2>/dev/null) || return 0
    now=$(date +%s)
    diff=$((now - ${ts%.*}))
    [[ $diff -gt $STALE_THRESHOLD ]]
}

# Get saved session ID
get_session_id() {
    if [[ -f "$SESSION_FILE" ]]; then
        jq -r '.session_id // ""' "$SESSION_FILE" 2>/dev/null || echo ""
    else
        echo ""
    fi
}

# Restart Claude Code in the target pane
restart_claude() {
    local session_id
    session_id=$(get_session_id)

    log "Restarting Claude Code..."

    if [[ -n "$session_id" ]]; then
        log "Resuming session: $session_id"
        tmux send-keys -t "$TMUX_PANE" "cd $SIBYL_ROOT && claude --resume $session_id" Enter
    else
        log "No session ID found, using --continue"
        tmux send-keys -t "$TMUX_PANE" "cd $SIBYL_ROOT && claude --continue" Enter
    fi

    # Wait for Claude to start (up to 60 seconds)
    local waited=0
    while ! claude_is_running && [[ $waited -lt 60 ]]; do
        sleep 5
        waited=$((waited + 5))
    done

    if claude_is_running; then
        log "Claude started, waiting 10s for initialization..."
        sleep 10
        # Inject resume command
        local project_name
        project_name=$(basename "$WORKSPACE")
        tmux send-keys -t "$TMUX_PANE" "/sibyl-research:continue $project_name" Enter
        log "Injected /sibyl-research:continue $project_name"
    else
        log "ERROR: Claude failed to start after 60s"
    fi
}

# Wake up an idle Claude session
wake_claude() {
    log "Waking idle Claude..."
    local project_name
    project_name=$(basename "$WORKSPACE")
    tmux send-keys -t "$TMUX_PANE" "/sibyl-research:continue $project_name" Enter
    log "Injected /sibyl-research:continue $project_name"
}

# ═══════════════════════════════════════════
# Main loop
# ═══════════════════════════════════════════

log "Starting Sibyl Sentinel"
log "  Workspace: $WORKSPACE"
log "  Target pane: $TMUX_PANE"
log "  Poll interval: ${POLL_INTERVAL}s"
log "  Stale threshold: ${STALE_THRESHOLD}s"
log ""

while true; do
    # Check for stop signal
    if [[ -f "$STOP_FILE" ]]; then
        log "Stop signal received, exiting."
        rm -f "$STOP_FILE"
        exit 0
    fi

    # Check if experiments/project are active
    if ! experiments_active; then
        log "No active work detected, sleeping..."
        sleep "$POLL_INTERVAL"
        continue
    fi

    # Check Claude process state
    if ! claude_is_running; then
        log "Claude not running! Experiments active, restarting..."
        sleep 5  # Brief wait to confirm it's truly dead
        if ! claude_is_running; then
            restart_claude
            # After restart, wait a full interval before next check
            sleep "$POLL_INTERVAL"
            continue
        fi
    fi

    # Claude is running - check if it's making progress
    if heartbeat_stale; then
        log "Heartbeat stale (>${STALE_THRESHOLD}s), Claude may be idle"
        # Double-check: is Claude waiting for user input?
        # If heartbeat is stale AND experiments active, nudge it
        wake_claude
    else
        log "OK - Claude running, heartbeat fresh"
    fi

    sleep "$POLL_INTERVAL"
done
```

**Step 2: Make executable and test manually**

Run: `chmod +x sibyl/sentinel.sh`
Run: `bash -n sibyl/sentinel.sh` (syntax check)
Expected: No errors

**Step 3: Write a basic integration test**

Create `tests/test_sentinel_script.sh`:

```bash
#!/bin/bash
# Basic syntax and help test for sentinel.sh
set -euo pipefail

SCRIPT="$(dirname "$0")/../sibyl/sentinel.sh"

# Test 1: syntax check
echo "Test 1: Syntax check..."
bash -n "$SCRIPT"
echo "PASS"

# Test 2: missing args
echo "Test 2: Missing args..."
if bash "$SCRIPT" 2>/dev/null; then
    echo "FAIL: should have errored on missing args"
    exit 1
fi
echo "PASS"

echo "All sentinel script tests passed."
```

**Step 4: Commit**

```bash
git add sibyl/sentinel.sh tests/test_sentinel_script.sh
git commit -m "feat(sentinel): create watchdog bash script"
```

---

### Task 4: Integrate Sentinel into plugin commands

**Files:**
- Modify: `plugin/commands/start.md` (save session ID + launch sentinel pane)
- Modify: `plugin/commands/stop.md` (write sentinel stop signal)
- Modify: `plugin/commands/resume.md` (update session ID + restart sentinel)

**Step 1: Add session ID save to start.md**

After step 2 ("记录返回的 `workspace_path` 和 `project_name`"), add:

```markdown
2.5. **保存 Session ID 供 Sentinel 使用**：
   ```bash
   cd $SIBYL_ROOT && .venv/bin/python3 -c "
   from sibyl.orchestrate import cli_sentinel_session
   cli_sentinel_session('WORKSPACE_PATH', '$CLAUDE_CODE_SESSION_ID')
   "
   ```
```

After step 3 (Ralph Loop), add:

```markdown
4. **启动 Sentinel 看门狗**（在 tmux 的 sibling pane 中）：
   ```bash
   # 检测当前是否在 tmux 中
   if [ -n "${TMUX:-}" ]; then
     # 在当前 window 右侧创建窄 pane 运行 sentinel
     CURRENT_WINDOW=$(tmux display-message -p '#{window_index}')
     SENTINEL_PANE=$(tmux split-window -t "$CURRENT_WINDOW" -h -l 50 -P -F '#{pane_id}' \
       "bash $SIBYL_ROOT/sibyl/sentinel.sh WORKSPACE_PATH \$(tmux display-message -p '#{pane_id}' -t $CURRENT_WINDOW.0)")
     tmux select-pane -t "$CURRENT_WINDOW.0"  # 焦点切回主 pane
     echo "🛡️ Sentinel 已启动: pane $SENTINEL_PANE"
   else
     echo "⚠️ 未检测到 tmux，Sentinel 未启动。建议在 tmux session 中运行以获得自动恢复能力。"
   fi
   ```
```

**Step 2: Add stop signal to stop.md**

Before step 2 (cancel Ralph Loop), add:

```markdown
1.5. 停止 Sentinel 看门狗：
   ```bash
   echo '{"stop": true}' > workspaces/$ARGUMENTS/sentinel_stop.json
   ```
```

**Step 3: Add session ID update to resume.md**

After step 2 ("获取当前状态"), add:

```markdown
2.5. **更新 Session ID 供 Sentinel 使用**：
   ```bash
   cd $SIBYL_ROOT && .venv/bin/python3 -c "
   from sibyl.orchestrate import cli_sentinel_session
   cli_sentinel_session('workspaces/$ARGUMENTS', '$CLAUDE_CODE_SESSION_ID')
   "
   ```
```

After step 3 (Ralph Loop), add the same sentinel launch block as start.md step 4.

**Step 4: Commit**

```bash
git add plugin/commands/start.md plugin/commands/stop.md plugin/commands/resume.md
git commit -m "feat(sentinel): integrate watchdog into start/stop/resume commands"
```

---

### Task 5: Add sentinel CLI reference to CLAUDE.md

**Files:**
- Modify: `CLAUDE.md` (add Sentinel section)

**Step 1: Add Sentinel documentation**

Add after the "实验等待轮询" section:

```markdown
### Sentinel 看门狗（自动恢复）
Sentinel 是纯 bash 看门狗脚本，跑在 tmux 的 sibling pane 中，确保实验轮询不中断。
- **心跳文件**: `<workspace>/sentinel_heartbeat.json`（cli_next/cli_record 自动写入）
- **Session 持久化**: `<workspace>/sentinel_session.json`（start/resume 时保存）
- **停止信号**: `<workspace>/sentinel_stop.json`（stop 时写入）
- **检测逻辑**: 每 2 分钟检查 Claude 进程 + 心跳新鲜度 + 实验状态
- **唤醒策略**:
  - 进程不存在 → `claude --resume <session_id>` + `/sibyl-research:continue`
  - 进程在但心跳 >5min → 注入 `/sibyl-research:continue`
- **CLI**: `cli_sentinel_session(workspace, session_id)`, `cli_sentinel_config(workspace)`
```

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add Sentinel watchdog documentation to CLAUDE.md"
```

---

### Task 6: End-to-end verification

**Step 1: Run all tests**

Run: `.venv/bin/python3 -m pytest tests/test_sentinel.py -v`
Run: `bash tests/test_sentinel_script.sh`

**Step 2: Manual smoke test**

1. Start a tmux session: `tmux new -s sibyl-test`
2. Run: `bash sibyl/sentinel.sh workspaces/ttt-dlm sibyl-test:0.0`
   - Should print "No active work detected" and sleep
3. In another pane, write a fake heartbeat to verify detection
4. Kill the sentinel with Ctrl+C or stop file

**Step 3: Final commit and push**

```bash
git push
```
