"""Experiment recovery: detect and recover from interrupted experiments.

Manages experiment state independently from gpu_progress.json, providing
richer tracking (PID files, recovery logs, detection scripts) for crash
recovery on shared GPU servers.

State file: exp/experiment_state.json (relative to workspace root)
"""

import datetime
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path


STATE_FILE = "exp/experiment_state.json"


@dataclass
class ExperimentState:
    """Persistent state for experiment recovery."""

    schema_version: int = 1
    tasks: dict = field(default_factory=dict)
    last_recovery_at: str = ""
    recovery_log: list = field(default_factory=list)


def load_experiment_state(workspace_root: Path) -> ExperimentState:
    """Load experiment state from disk, returning empty state if not found."""
    state_path = workspace_root / STATE_FILE
    if not state_path.exists():
        return ExperimentState()
    try:
        with open(state_path, encoding="utf-8") as f:
            data = json.load(f)
        return ExperimentState(
            schema_version=data.get("schema_version", 1),
            tasks=data.get("tasks", {}),
            last_recovery_at=data.get("last_recovery_at", ""),
            recovery_log=data.get("recovery_log", []),
        )
    except (json.JSONDecodeError, OSError):
        return ExperimentState()


def save_experiment_state(workspace_root: Path, state: ExperimentState) -> None:
    """Save experiment state to disk."""
    state_path = workspace_root / STATE_FILE
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(asdict(state), f, indent=2)


def register_task(
    state: ExperimentState,
    task_id: str,
    gpu_ids: list[int],
    pid_file: str = "",
) -> None:
    """Register a task as running in the experiment state."""
    state.tasks[task_id] = {
        "status": "running",
        "gpu_ids": gpu_ids,
        "pid_file": pid_file,
        "registered_at": datetime.datetime.now().isoformat(),
    }


def register_dispatched_tasks(
    workspace_root: Path,
    task_gpu_map: dict[str, list[int]],
    remote_project_dir: str,
) -> ExperimentState:
    """Register dispatched tasks in both experiment_state and gpu_progress."""
    from sibyl.gpu_scheduler import register_running_tasks

    state = load_experiment_state(workspace_root)
    for task_id, gpu_ids in task_gpu_map.items():
        pid_file = f"{remote_project_dir}/exp/results/{task_id}.pid"
        register_task(state, task_id, gpu_ids=gpu_ids, pid_file=pid_file)

    save_experiment_state(workspace_root, state)
    register_running_tasks(workspace_root, task_gpu_map)
    return state


# ---------------------------------------------------------------------------
# SSH Batch Detection Script
# ---------------------------------------------------------------------------


def generate_detection_script(remote_project_dir: str, task_ids: list[str]) -> str:
    """Generate a bash script that checks task status on a remote server.

    For each task, checks (in order):
    1. DONE marker file -> DONE:task_id:json
    2. PID file + process alive -> RUNNING:task_id:progress_json
    3. PID file + process dead -> DEAD:task_id:pid
    4. Neither -> UNKNOWN:task_id
    """
    task_ids_str = " ".join(task_ids)
    return f'''cd "{remote_project_dir}" 2>/dev/null || exit 1
for task_id in {task_ids_str}; do
  if [ -f "exp/results/${{task_id}}_DONE" ]; then
    content=$(cat "exp/results/${{task_id}}_DONE" 2>/dev/null || echo '{{}}')
    echo "DONE:${{task_id}}:${{content}}"
  elif [ -f "exp/results/${{task_id}}.pid" ]; then
    pid=$(cat "exp/results/${{task_id}}.pid")
    if kill -0 "$pid" 2>/dev/null; then
      progress=$(cat "exp/results/${{task_id}}_PROGRESS.json" 2>/dev/null || echo '{{}}')
      echo "RUNNING:${{task_id}}:${{progress}}"
    else
      echo "DEAD:${{task_id}}:${{pid}}"
    fi
  else
    echo "UNKNOWN:${{task_id}}"
  fi
done'''


def parse_detection_output(output: str) -> dict:
    """Parse output from the detection script.

    Each line has format STATUS:task_id:payload
    Returns dict keyed by task_id with detection info.
    """
    results = {}
    for line in output.strip().splitlines():
        line = line.strip()
        if not line:
            continue

        if line.startswith("DONE:"):
            # DONE:task_id:json_payload
            _, rest = line.split(":", 1)
            task_id, json_str = rest.split(":", 1)
            try:
                done_info = json.loads(json_str)
            except (json.JSONDecodeError, ValueError):
                done_info = {}
            results[task_id] = {
                "detected_status": "done",
                "done_info": done_info,
            }
        elif line.startswith("RUNNING:"):
            _, rest = line.split(":", 1)
            task_id, json_str = rest.split(":", 1)
            try:
                progress = json.loads(json_str)
            except (json.JSONDecodeError, ValueError):
                progress = {}
            results[task_id] = {
                "detected_status": "running",
                "progress": progress,
            }
        elif line.startswith("DEAD:"):
            _, rest = line.split(":", 1)
            task_id, pid_str = rest.split(":", 1)
            results[task_id] = {
                "detected_status": "dead",
                "dead_pid": pid_str,
            }
        elif line.startswith("UNKNOWN:"):
            _, task_id = line.split(":", 1)
            results[task_id] = {
                "detected_status": "unknown",
            }

    return results


# ---------------------------------------------------------------------------
# Core Recovery Logic
# ---------------------------------------------------------------------------


@dataclass
class RecoveryResult:
    """Result of applying detection output to experiment state."""

    recovered_completed: list = field(default_factory=list)
    still_running: list = field(default_factory=list)
    recovered_failed: list = field(default_factory=list)
    ssh_unreachable: bool = False
    needs_monitor: bool = False
    progress: dict = field(default_factory=dict)


def get_running_tasks(state: ExperimentState) -> list[str]:
    """Return task IDs that are currently in 'running' status."""
    return [tid for tid, info in state.tasks.items() if info.get("status") == "running"]


def recover_from_detection(
    state: ExperimentState, detection: dict
) -> RecoveryResult:
    """Apply detection results to experiment state in-place.

    Args:
        state: ExperimentState to update (modified in-place)
        detection: Output from parse_detection_output()

    Returns:
        RecoveryResult summarizing what happened
    """
    result = RecoveryResult()
    now = datetime.datetime.now().isoformat()
    log_entries = []

    for task_id, info in detection.items():
        status = info.get("detected_status", "unknown")

        if status == "done":
            done_info = info.get("done_info", {})
            exit_code = done_info.get("exit_code", 0)
            if exit_code == 0:
                state.tasks[task_id]["status"] = "completed"
                result.recovered_completed.append(task_id)
                log_entries.append(f"[{now}] {task_id}: recovered as completed")
            else:
                state.tasks[task_id]["status"] = "failed"
                result.recovered_failed.append(task_id)
                log_entries.append(
                    f"[{now}] {task_id}: recovered as failed (exit_code={exit_code})"
                )
        elif status == "running":
            result.still_running.append(task_id)
            result.progress[task_id] = info.get("progress", {})
        elif status == "dead":
            state.tasks[task_id]["status"] = "failed"
            state.tasks[task_id]["error_summary"] = "process_disappeared"
            result.recovered_failed.append(task_id)
            dead_pid = info.get("dead_pid", "?")
            log_entries.append(
                f"[{now}] {task_id}: process dead (pid={dead_pid}), marked failed"
            )
        else:  # unknown
            state.tasks[task_id]["status"] = "failed"
            state.tasks[task_id]["error_summary"] = "unknown_status"
            result.recovered_failed.append(task_id)
            log_entries.append(f"[{now}] {task_id}: unknown status, marked failed")

    result.needs_monitor = len(result.still_running) > 0

    if log_entries:
        state.recovery_log.extend(log_entries)
        state.last_recovery_at = now

    return result


# ---------------------------------------------------------------------------
# State Sync with gpu_progress.json
# ---------------------------------------------------------------------------

GPU_PROGRESS_FILE = "exp/gpu_progress.json"


def _load_gpu_progress(workspace_root: Path) -> dict:
    """Load gpu_progress.json, returning default structure if missing."""
    path = workspace_root / GPU_PROGRESS_FILE
    default = {"completed": [], "failed": [], "running": {}, "timings": {}}
    if not path.exists():
        return default
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for k in default:
            if k not in data:
                data[k] = type(default[k])()
        return data
    except (json.JSONDecodeError, OSError):
        return default


def _save_gpu_progress(workspace_root: Path, data: dict) -> None:
    """Write gpu_progress.json with file locking to prevent race conditions."""
    from sibyl.gpu_scheduler import _progress_lock
    path = workspace_root / GPU_PROGRESS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with _progress_lock(workspace_root):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)


def sync_to_gpu_progress(workspace_root: Path, state: ExperimentState) -> None:
    """Sync experiment_state to gpu_progress.json.

    - completed tasks: remove from running, add to completed
    - failed tasks: remove from running, add to failed
    - running tasks: backfill into running if missing
    """
    gp = _load_gpu_progress(workspace_root)

    for task_id, info in state.tasks.items():
        status = info.get("status", "")

        if status == "completed":
            gp["running"].pop(task_id, None)
            if task_id not in gp["completed"]:
                gp["completed"].append(task_id)

        elif status == "failed":
            gp["running"].pop(task_id, None)
            if task_id not in gp.get("failed", []):
                gp.setdefault("failed", []).append(task_id)

        elif status == "running":
            if task_id not in gp["running"]:
                gp["running"][task_id] = {
                    "gpu_ids": info.get("gpu_ids", []),
                    "started_at": info.get("registered_at", ""),
                }

    _save_gpu_progress(workspace_root, gp)
    from sibyl.gpu_scheduler import sync_workspace_gpu_leases

    sync_workspace_gpu_leases(workspace_root, gp.get("running", {}))


def migrate_from_gpu_progress(workspace_root: Path) -> ExperimentState:
    """Create ExperimentState from existing gpu_progress.json.

    Used for initial migration when experiment_state.json doesn't exist yet.
    """
    gp = _load_gpu_progress(workspace_root)
    state = ExperimentState()

    for task_id in gp.get("completed", []):
        state.tasks[task_id] = {"status": "completed", "gpu_ids": []}

    for task_id in gp.get("failed", []):
        state.tasks[task_id] = {"status": "failed", "gpu_ids": []}

    for task_id, info in gp.get("running", {}).items():
        state.tasks[task_id] = {
            "status": "running",
            "gpu_ids": info.get("gpu_ids", []),
            "pid_file": "",
            "registered_at": info.get("started_at", ""),
        }

    return state
