"""GPU-aware task scheduler for experiment parallelization.

Reads task_plan.json for task definitions and depends_on graph,
tracks progress in exp/gpu_progress.json, and assigns GPU subsets
to independent tasks for parallel execution.

Task plan format:
    {
        "tasks": [
            {
                "id": "train_baseline",
                "depends_on": [],
                "gpu_count": 2,           // REQUIRED
                "estimated_minutes": 60   // REQUIRED
            },
            ...
        ]
    }

GPU polling:
    For shared servers, poll_free_gpus() checks nvidia-smi output to find
    GPUs with memory usage below a threshold. The polling is designed to be
    executed as a lightweight bash command (no LLM needed).
"""
import json
import re
from collections import deque
from pathlib import Path


# Required fields that planner must provide for each task
_REQUIRED_TASK_FIELDS = ("gpu_count", "estimated_minutes")


def validate_task_plan(tasks: list[dict]) -> list[str]:
    """Check that all tasks have required GPU scheduling fields.

    Returns list of task IDs missing required fields (empty = all valid).
    """
    incomplete = []
    for t in tasks:
        for field in _REQUIRED_TASK_FIELDS:
            if field not in t or t[field] is None:
                incomplete.append(t["id"])
                break
    return incomplete


def topo_sort_layers(tasks: list[dict]) -> list[list[dict]]:
    """BFS topological sort, grouping tasks by dependency layer.

    Each layer contains tasks whose dependencies are all in earlier layers.
    Returns list of layers, each layer is a list of task dicts.
    """
    if not tasks:
        return []

    task_map = {t["id"]: t for t in tasks}
    in_degree = {t["id"]: 0 for t in tasks}
    children = {t["id"]: [] for t in tasks}

    for t in tasks:
        for dep in t.get("depends_on", []):
            if dep in task_map:
                in_degree[t["id"]] += 1
                children[dep].append(t["id"])

    layers = []
    queue = deque([tid for tid, deg in in_degree.items() if deg == 0])

    while queue:
        layer = list(queue)
        queue.clear()
        layers.append([task_map[tid] for tid in layer])
        for tid in layer:
            for child in children[tid]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

    return layers


def assign_gpus(ready_tasks: list[dict], gpu_ids: list[int],
                default_gpus_per_task: int = 1) -> list[dict]:
    """Assign GPU subsets to ready tasks based on per-task gpu_count.

    Each task MUST declare gpu_count. Falls back to default_gpus_per_task
    only for legacy task plans that haven't been updated yet.

    Returns list of assignments:
        [{"task_ids": ["task_0a"], "gpu_ids": [0, 1]}, ...]

    Greedy allocation: assigns tasks in order until GPUs are exhausted.
    """
    if not ready_tasks or not gpu_ids:
        return []

    available = list(gpu_ids)
    assignments = []

    for task in ready_tasks:
        needed = task.get("gpu_count", default_gpus_per_task)
        needed = max(1, needed)  # at least 1 GPU

        if needed > len(available):
            break  # not enough GPUs for this task

        assigned = available[:needed]
        available = available[needed:]
        assignments.append({
            "task_ids": [task["id"]],
            "gpu_ids": assigned,
        })

        if not available:
            break

    # Edge case: no task could be assigned (first task needs more GPUs than total)
    if not assignments and ready_tasks:
        needed = ready_tasks[0].get("gpu_count", default_gpus_per_task)
        if needed > len(gpu_ids):
            # Give all GPUs to the first task anyway
            assignments = [{"task_ids": [ready_tasks[0]["id"]], "gpu_ids": list(gpu_ids)}]

    return assignments


def _compute_calibration_ratio(timings: dict) -> float:
    """Compute calibration ratio from historical task timings.

    Ratio = median(actual / planned) across completed tasks.
    Returns 1.0 if no valid timing data.

    A ratio < 1.0 means tasks finish faster than planned.
    A ratio > 1.0 means tasks take longer than planned.
    """
    ratios = []
    for timing in timings.values():
        planned = timing.get("planned_min", 0)
        actual = timing.get("actual_min", 0)
        if planned > 0 and actual > 0:
            ratios.append(actual / planned)
    if not ratios:
        return 1.0
    ratios.sort()
    n = len(ratios)
    if n % 2 == 0:
        return (ratios[n // 2 - 1] + ratios[n // 2]) / 2.0
    return ratios[n // 2]


def estimate_batch_minutes(batch: list[dict], tasks: list[dict],
                           default_minutes: int = 10,
                           timings: dict | None = None) -> int:
    """Estimate how long a batch will take (max of calibrated task estimates).

    Each task can declare estimated_minutes. The batch duration is the max
    across all tasks (since they run in parallel).

    If timings dict is provided (from gpu_progress.json), calibrates estimates
    using the median actual/planned ratio from previously completed tasks.
    For example, if past tasks consistently finished in 70% of estimated time,
    the ratio is 0.7 and future estimates are scaled down accordingly.

    Args:
        batch: List of task-GPU assignments
        tasks: Full task list from task_plan.json
        default_minutes: Fallback estimate when task has no estimate
        timings: Optional dict of {task_id: {planned_min, actual_min}} from completed tasks
    """
    if not batch:
        return default_minutes

    ratio = _compute_calibration_ratio(timings or {})

    task_map = {t["id"]: t for t in tasks}
    max_est = default_minutes

    for assignment in batch:
        for tid in assignment["task_ids"]:
            task = task_map.get(tid, {})
            # Use task-specific actual timing if available (re-run scenario)
            if timings and tid in timings and timings[tid].get("actual_min", 0) > 0:
                est = timings[tid]["actual_min"]
            else:
                est = task.get("estimated_minutes", default_minutes)
                est = max(1, int(est * ratio))  # calibrate with historical ratio
            if est > max_est:
                max_est = est

    return max_est


def _load_progress(workspace_root: Path) -> tuple[set, set, dict, dict]:
    """Load completed, running, and timing info from gpu_progress.json.

    Returns (completed_ids, running_ids, running_map, timings).
    running_map: {task_id: {"gpu_ids": [...], "started_at": "..."}}
    """
    progress_path = workspace_root / "exp" / "gpu_progress.json"
    completed = set()
    running_map = {}
    timings = {}
    if progress_path.exists():
        try:
            with open(progress_path, encoding="utf-8") as f:
                progress = json.load(f)
            completed = set(progress.get("completed", []))
            running_map = progress.get("running", {})
            timings = progress.get("timings", {})
        except (json.JSONDecodeError, OSError):
            pass
    return completed, set(running_map.keys()), running_map, timings


def register_running_tasks(workspace_root: Path, task_gpu_map: dict[str, list[int]]) -> None:
    """Register tasks as running in gpu_progress.json.

    Args:
        workspace_root: Path to workspace directory
        task_gpu_map: {task_id: [gpu_ids]} mapping of tasks to assigned GPUs
    """
    import datetime
    progress_path = workspace_root / "exp" / "gpu_progress.json"
    progress_path.parent.mkdir(parents=True, exist_ok=True)

    progress = {"completed": [], "failed": [], "running": {}, "timings": {}}
    if progress_path.exists():
        try:
            with open(progress_path, encoding="utf-8") as f:
                progress.update(json.load(f))
        except (json.JSONDecodeError, OSError):
            pass

    if "running" not in progress:
        progress["running"] = {}

    now = datetime.datetime.now().isoformat()
    for task_id, gpu_ids in task_gpu_map.items():
        progress["running"][task_id] = {
            "gpu_ids": gpu_ids,
            "started_at": now,
        }

    with open(progress_path, "w", encoding="utf-8") as f:
        json.dump(progress, f, indent=2)


def unregister_running_task(workspace_root: Path, task_id: str) -> None:
    """Remove a task from the running map in gpu_progress.json.

    Called when a task completes (the experimenter also adds it to 'completed').
    """
    progress_path = workspace_root / "exp" / "gpu_progress.json"
    if not progress_path.exists():
        return
    try:
        with open(progress_path, encoding="utf-8") as f:
            progress = json.load(f)
    except (json.JSONDecodeError, OSError):
        return
    running = progress.get("running", {})
    if task_id in running:
        del running[task_id]
        progress["running"] = running
        with open(progress_path, "w", encoding="utf-8") as f:
            json.dump(progress, f, indent=2)


def get_running_gpu_ids(workspace_root: Path) -> list[int]:
    """Get GPU IDs currently occupied by running tasks."""
    _, _, running_map, _ = _load_progress(workspace_root)
    occupied = set()
    for info in running_map.values():
        occupied.update(info.get("gpu_ids", []))
    return sorted(occupied)


def get_next_batch(workspace_root: Path, gpu_ids: list[int], mode: str = "PILOT",
                   gpus_per_task: int = 1) -> list[dict] | None:
    """Get the next batch of experiment tasks to execute.

    Args:
        workspace_root: Path to workspace directory
        gpu_ids: Available GPU IDs
        mode: "PILOT" or "FULL"
        gpus_per_task: Default GPUs per task (overridden by task-level gpu_count)

    Returns:
        None: No task_plan.json or no tasks array → fallback to single-agent
        []: Tasks exist but all blocked by dependencies
        [assignments]: Next batch of task-GPU assignments
    """
    task_plan_path = workspace_root / "plan" / "task_plan.json"
    if not task_plan_path.exists():
        return None

    try:
        with open(task_plan_path, encoding="utf-8") as f:
            plan = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    tasks = plan.get("tasks")
    if not tasks or not isinstance(tasks, list):
        return None

    # Load progress (completed + running)
    completed, running_ids, _, _ = _load_progress(workspace_root)

    # Filter out completed AND running tasks
    excluded = completed | running_ids
    remaining = [t for t in tasks if t["id"] not in excluded]
    if not remaining:
        # Check if there are running tasks (not truly done yet)
        if running_ids:
            return []  # Still running, nothing new to schedule
        return None  # All done

    # Find ready tasks (all deps completed, not already running)
    ready = [
        t for t in remaining
        if all(dep in completed for dep in t.get("depends_on", []))
    ]

    if not ready:
        return []  # Blocked

    return assign_gpus(ready, gpu_ids, gpus_per_task)


def get_batch_info(workspace_root: Path, gpu_ids: list[int], mode: str = "PILOT",
                   gpus_per_task: int = 1) -> dict | None:
    """Get next batch with metadata (assignments + estimated time).

    Returns None if no task_plan, or dict:
        {
            "batch": [assignments],
            "estimated_minutes": int,
            "remaining_count": int,
            "total_count": int,
        }
    Returns {"batch": [], ...} if blocked.
    """
    task_plan_path = workspace_root / "plan" / "task_plan.json"
    if not task_plan_path.exists():
        return None

    try:
        with open(task_plan_path, encoding="utf-8") as f:
            plan = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    tasks = plan.get("tasks")
    if not tasks or not isinstance(tasks, list):
        return None

    # Load progress (completed + running)
    completed, running_ids, _, timings = _load_progress(workspace_root)

    # Filter out completed AND running tasks
    excluded = completed | running_ids
    remaining = [t for t in tasks if t["id"] not in excluded]
    if not remaining:
        if running_ids:
            return {"batch": [], "estimated_minutes": 0,
                    "remaining_count": len(running_ids), "total_count": len(tasks)}
        return None

    ready = [
        t for t in remaining
        if all(dep in completed for dep in t.get("depends_on", []))
    ]

    if not ready:
        return {"batch": [], "estimated_minutes": 0,
                "remaining_count": len(remaining) + len(running_ids),
                "total_count": len(tasks)}

    batch = assign_gpus(ready, gpu_ids, gpus_per_task)
    est = estimate_batch_minutes(batch, tasks, timings=timings)

    # Compute calibration info for description
    ratio = _compute_calibration_ratio(timings)
    calibrated = len(timings) > 0 and any(
        t.get("actual_min", 0) > 0 for t in timings.values()
    )

    return {
        "batch": batch,
        "estimated_minutes": est,
        "remaining_count": len(remaining),
        "total_count": len(tasks),
        "calibration_ratio": round(ratio, 2),
        "calibrated": calibrated,
    }


# ---------------------------------------------------------------------------
# GPU availability polling for shared servers
# ---------------------------------------------------------------------------

# Threshold: GPU is "free" if used memory is below this (MB)
DEFAULT_FREE_THRESHOLD_MB = 2000


def nvidia_smi_query_cmd(include_total: bool = False) -> str:
    """Return the nvidia-smi command to query GPU memory usage.

    Args:
        include_total: If True, also query memory.total for percentage calculation.

    Output format (include_total=False): "index, memory.used"
    Output format (include_total=True):  "index, memory.used, memory.total"
    """
    fields = "index,memory.used"
    if include_total:
        fields += ",memory.total"
    return f"nvidia-smi --query-gpu={fields} --format=csv,noheader,nounits"


def parse_free_gpus(
    nvidia_smi_output: str,
    threshold_mb: int = DEFAULT_FREE_THRESHOLD_MB,
    max_gpus: int = 0,
    aggressive_mode: bool = False,
    aggressive_threshold_pct: int = 25,
) -> list[int]:
    """Parse nvidia-smi CSV output and return GPU IDs considered available.

    Two strategies:
    1. Normal mode: GPU is "free" if memory usage < threshold_mb (e.g., 2000 MB)
    2. Aggressive mode: ALSO consider GPUs with usage < aggressive_threshold_pct% of total VRAM.
       This catches GPUs that are allocated but mostly idle on shared servers.
       Requires nvidia-smi output to include memory.total (3 columns).

    Args:
        nvidia_smi_output: Raw output from nvidia_smi_query_cmd()
        threshold_mb: Memory usage threshold in MB; GPUs below this are "free"
        max_gpus: Maximum number of GPUs to return; 0 = no limit
        aggressive_mode: Enable aggressive GPU claiming
        aggressive_threshold_pct: VRAM usage % below which GPU is claimed (aggressive mode)

    Returns:
        Sorted list of free GPU IDs (up to max_gpus)
    """
    free = []
    for line in nvidia_smi_output.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = re.split(r"[,\s]+", line)
        if len(parts) < 2:
            continue
        try:
            gpu_id = int(parts[0])
            mem_used = int(float(parts[1]))
        except (ValueError, IndexError):
            continue

        # Normal mode: absolute threshold
        if mem_used < threshold_mb:
            free.append(gpu_id)
            continue

        # Aggressive mode: percentage threshold
        if aggressive_mode and len(parts) >= 3:
            try:
                mem_total = int(float(parts[2]))
                if mem_total > 0:
                    usage_pct = (mem_used / mem_total) * 100
                    if usage_pct < aggressive_threshold_pct:
                        free.append(gpu_id)
            except (ValueError, IndexError):
                pass

    free = sorted(free)
    if max_gpus > 0:
        free = free[:max_gpus]
    return free


def gpu_poll_wait_script(
    ssh_server: str,
    candidate_gpu_ids: list[int],
    threshold_mb: int = DEFAULT_FREE_THRESHOLD_MB,
    poll_interval_sec: int = 600,
    max_polls: int = 0,
    marker_file: str = "/tmp/sibyl_gpu_free.json",
    aggressive_mode: bool = False,
    aggressive_threshold_pct: int = 25,
) -> str:
    """Generate a bash script that polls for free GPUs via SSH.

    The script:
    1. Runs nvidia-smi on the remote server every poll_interval_sec seconds
    2. Checks if any candidate GPU has memory below threshold
    3. In aggressive mode, also claims GPUs with <aggressive_threshold_pct% VRAM usage
    4. When free GPUs are found, writes them to marker_file and exits 0
    5. If max_polls > 0, exits 1 after that many attempts (timeout)
    6. If max_polls == 0 (default), polls indefinitely until GPUs are free

    This runs as a pure bash command — no LLM tokens consumed during polling.

    Args:
        ssh_server: SSH host to connect to
        candidate_gpu_ids: GPU IDs to check
        threshold_mb: Free memory threshold in MB
        poll_interval_sec: Seconds between polls (default 600 = 10 min)
        max_polls: Maximum poll attempts; 0 = infinite (no timeout)
        marker_file: Path to write free GPU IDs JSON when found
        aggressive_mode: Also claim GPUs with low VRAM usage percentage
        aggressive_threshold_pct: VRAM usage % threshold for aggressive mode

    Returns:
        Bash script string
    """
    gpu_ids_str = ",".join(str(g) for g in candidate_gpu_ids)
    limit_label = f"max {max_polls}" if max_polls > 0 else "unlimited"

    if max_polls > 0:
        loop_header = f"for i in $(seq 1 {max_polls}); do"
        loop_footer = f"""done

echo "Timeout after {max_polls} polls ({max_polls * poll_interval_sec}s)"
exit 1"""
    else:
        loop_header = "i=0\nwhile true; do\n    i=$((i + 1))"
        loop_footer = "done"

    # Aggressive mode needs memory.total for percentage calculation
    if aggressive_mode:
        smi_fields = "index,memory.used,memory.total"
        aggressive_check = f"""
        # Aggressive mode: also claim GPUs with <{aggressive_threshold_pct}% VRAM usage
        if [ -n "$total" ] && [ "$total" -gt 0 ] 2>/dev/null; then
            pct=$(( mem * 100 / total ))
            if [ "$pct" -lt {aggressive_threshold_pct} ] 2>/dev/null; then
                if [ -z "$FREE_GPUS" ]; then
                    FREE_GPUS="$idx"
                else
                    FREE_GPUS="$FREE_GPUS,$idx"
                fi
            fi
        fi"""
        read_line = 'while IFS=\',\' read -r idx mem total; do'
        clean_vars = """        idx=$(echo "$idx" | tr -d ' ')
        mem=$(echo "$mem" | tr -d ' ')
        total=$(echo "$total" | tr -d ' ')"""
        mode_label = f"aggressive (<{aggressive_threshold_pct}% VRAM)"
    else:
        smi_fields = "index,memory.used"
        aggressive_check = ""
        read_line = "while IFS=',' read -r idx mem; do"
        clean_vars = """        idx=$(echo "$idx" | tr -d ' ')
        mem=$(echo "$mem" | tr -d ' ')"""
        mode_label = "normal"

    return f'''#!/bin/bash
# Sibyl GPU poll: wait for free GPUs on {ssh_server}
# Candidates: [{gpu_ids_str}], threshold: {threshold_mb}MB, mode: {mode_label}
# Poll every {poll_interval_sec}s, {limit_label} attempts

MARKER="{marker_file}"
rm -f "$MARKER"

{loop_header}
    OUTPUT=$(ssh {ssh_server} "nvidia-smi --query-gpu={smi_fields} --format=csv,noheader,nounits" 2>/dev/null)
    if [ $? -ne 0 ]; then
        echo "[poll $i] SSH failed, retrying in {poll_interval_sec}s..."
        sleep {poll_interval_sec}
        continue
    fi

    # Parse free GPUs
    FREE_GPUS=""
    {read_line}
{clean_vars}
        # Check if this GPU is in our candidate list
        case ",{gpu_ids_str}," in
            *",$idx,"*)
                if [ "$mem" -lt {threshold_mb} ] 2>/dev/null; then
                    if [ -z "$FREE_GPUS" ]; then
                        FREE_GPUS="$idx"
                    else
                        FREE_GPUS="$FREE_GPUS,$idx"
                    fi
                fi{aggressive_check}
                ;;
        esac
    done <<< "$OUTPUT"

    if [ -n "$FREE_GPUS" ]; then
        echo "[poll $i] Found free GPUs: $FREE_GPUS"
        echo "{{\\"free_gpus\\": [$FREE_GPUS], \\"poll_count\\": $i}}" > "$MARKER"
        exit 0
    fi

    echo "[poll $i] No free GPUs (all above {threshold_mb}MB), waiting {poll_interval_sec}s..."
    sleep {poll_interval_sec}
{loop_footer}
'''


def experiment_monitor_script(
    ssh_server: str,
    remote_project_dir: str,
    task_ids: list[str],
    poll_interval_sec: int = 300,
    timeout_minutes: int = 0,
    marker_file: str = "/tmp/sibyl_exp_monitor.json",
    notify_cmd: str = "",
) -> str:
    """Generate a bash script that monitors running experiments via SSH.

    The script:
    1. Periodically checks for DONE marker files on the remote server
    2. Collects gpu_progress.json updates from completed tasks
    3. Writes status to local marker_file for the orchestrator to read
    4. Optionally runs notify_cmd when tasks complete (e.g., lark notification)
    5. Exits when all monitored tasks have DONE markers or on timeout

    This runs as a pure bash background job — no LLM tokens consumed.

    Args:
        ssh_server: SSH host to connect to
        remote_project_dir: Remote project directory (e.g., /home/user/sibyl_system/projects/ttt-dlm)
        task_ids: List of task IDs to monitor
        poll_interval_sec: Seconds between checks (default 300 = 5 min)
        timeout_minutes: Maximum monitoring time; 0 = unlimited
        marker_file: Local path to write monitoring status JSON
        notify_cmd: Optional shell command to run on completion (e.g., curl webhook)

    Returns:
        Bash script string
    """
    task_ids_str = " ".join(task_ids)
    task_count = len(task_ids)

    if timeout_minutes > 0:
        timeout_sec = timeout_minutes * 60
        timeout_check = f"""
    elapsed=$(( $(date +%s) - start_time ))
    if [ "$elapsed" -gt {timeout_sec} ]; then
        echo "[monitor] Timeout after {timeout_minutes}min"
        echo '{{"status": "timeout", "completed": ['$COMPLETED_JSON'], "pending": ['$PENDING_JSON'], "elapsed_sec": '$elapsed'}}' > "$MARKER"
        exit 1
    fi"""
    else:
        timeout_check = ""

    notify_block = ""
    if notify_cmd:
        notify_block = f"""
        # Notification on task completion
        {notify_cmd}"""

    return f'''#!/bin/bash
# Sibyl Experiment Monitor: watch for task completion on {ssh_server}
# Tasks: {task_ids_str}
# Poll every {poll_interval_sec}s, timeout: {"unlimited" if timeout_minutes == 0 else f"{timeout_minutes}min"}

MARKER="{marker_file}"
REMOTE_DIR="{remote_project_dir}"
ALL_TASKS=({task_ids_str})
TOTAL={task_count}
start_time=$(date +%s)
PREV_DONE_COUNT=0

echo '{{"status": "monitoring", "total": {task_count}, "completed": [], "pending": {json.dumps(task_ids)}, "just_completed": [], "dispatch_needed": false}}' > "$MARKER"

i=0
while true; do
    i=$((i + 1))
    COMPLETED=""
    COMPLETED_JSON=""
    PENDING=""
    PENDING_JSON=""
    JUST_COMPLETED=""
    JUST_COMPLETED_JSON=""
    done_count=0

    for task_id in "${{ALL_TASKS[@]}}"; do
        # Check for DONE marker file on remote server
        result=$(ssh {ssh_server} "test -f $REMOTE_DIR/exp/results/${{task_id}}_DONE && echo 'DONE' || echo 'PENDING'" 2>/dev/null)

        if [ "$result" = "DONE" ]; then
            done_count=$((done_count + 1))
            if [ -z "$COMPLETED" ]; then
                COMPLETED="$task_id"
                COMPLETED_JSON="\\"$task_id\\""
            else
                COMPLETED="$COMPLETED,$task_id"
                COMPLETED_JSON="$COMPLETED_JSON, \\"$task_id\\""
            fi
        else
            if [ -z "$PENDING" ]; then
                PENDING="$task_id"
                PENDING_JSON="\\"$task_id\\""
            else
                PENDING="$PENDING,$task_id"
                PENDING_JSON="$PENDING_JSON, \\"$task_id\\""
            fi
        fi
    done

    # Detect newly completed tasks since last poll
    DISPATCH="false"
    if [ "$done_count" -gt "$PREV_DONE_COUNT" ]; then
        DISPATCH="true"
    fi
    PREV_DONE_COUNT=$done_count

    elapsed=$(( $(date +%s) - start_time ))
    echo "[monitor $i] $done_count/$TOTAL done (elapsed: ${{elapsed}}s)"

    # Write status to marker file
    if [ "$done_count" -eq "$TOTAL" ]; then
        echo '{{"status": "all_complete", "completed": ['$COMPLETED_JSON'], "pending": [], "just_completed": [], "dispatch_needed": false, "elapsed_sec": '$elapsed', "poll_count": '$i'}}' > "$MARKER"
        echo "[monitor] All {task_count} tasks complete!"{notify_block}
        exit 0
    fi

    echo '{{"status": "monitoring", "completed": ['$COMPLETED_JSON'], "pending": ['$PENDING_JSON'], "just_completed": [], "dispatch_needed": '$DISPATCH', "elapsed_sec": '$elapsed', "poll_count": '$i'}}' > "$MARKER"
{timeout_check}
    sleep {poll_interval_sec}
done
'''


def read_monitor_result(marker_file: str = "/tmp/sibyl_exp_monitor.json") -> dict | None:
    """Read the experiment monitor status file.

    Returns dict with status, completed tasks, pending tasks, etc.
    Returns None if file doesn't exist.
    """
    path = Path(marker_file)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def read_poll_result(marker_file: str = "/tmp/sibyl_gpu_free.json") -> list[int] | None:
    """Read the marker file written by gpu_poll_wait_script.

    Returns list of free GPU IDs, or None if file doesn't exist.
    """
    path = Path(marker_file)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("free_gpus", [])
    except (json.JSONDecodeError, OSError):
        return None
