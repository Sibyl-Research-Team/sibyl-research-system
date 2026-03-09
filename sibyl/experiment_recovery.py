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
