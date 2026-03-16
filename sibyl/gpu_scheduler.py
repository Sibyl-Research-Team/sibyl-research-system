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
import fcntl
import json
import re
import shlex
import time
from collections import deque
from contextlib import contextmanager
from pathlib import Path

from sibyl._paths import get_system_state_dir


@contextmanager
def _progress_lock(workspace_root: Path, timeout_sec: float = 30.0):
    """Acquire an exclusive file lock for gpu_progress.json operations.

    Prevents race conditions when multiple agents read-modify-write the same file.
    Uses LOCK_NB + retry loop with timeout to avoid deadlocks.
    """
    lock_path = workspace_root / "exp" / ".gpu_progress.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = open(lock_path, "w")
    deadline = time.monotonic() + timeout_sec
    acquired = False
    try:
        while time.monotonic() < deadline:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                time.sleep(0.1)
        if not acquired:
            # Force-break stale lock after timeout
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        yield
    finally:
        if acquired:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


def _global_gpu_leases_path() -> Path:
    """Return the repo-scoped global GPU lease file."""
    state_dir = get_system_state_dir() / "scheduler"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "gpu_leases.json"


@contextmanager
def _global_gpu_leases_lock(timeout_sec: float = 30.0):
    """Serialize cross-project GPU lease updates with timeout."""
    lock_path = _global_gpu_leases_path().with_suffix(".lock")
    lock_fd = open(lock_path, "w", encoding="utf-8")
    deadline = time.monotonic() + timeout_sec
    acquired = False
    try:
        while time.monotonic() < deadline:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                time.sleep(0.1)
        if not acquired:
            # Force-break stale lock after timeout
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        yield
    finally:
        if acquired:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


def _load_global_gpu_leases_unlocked() -> dict[str, dict]:
    path = _global_gpu_leases_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    leases = data.get("leases", data)
    if not isinstance(leases, dict):
        return {}
    return {
        str(gpu_id): lease
        for gpu_id, lease in leases.items()
        if isinstance(lease, dict)
    }


def _save_global_gpu_leases_unlocked(leases: dict[str, dict]) -> None:
    path = _global_gpu_leases_path()
    tmp = path.with_suffix(".tmp")
    payload = {
        "leases": leases,
        "updated_at": time.time(),
    }
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def _lease_entry_matches_running(gpu_id: int, entry: dict) -> bool:
    workspace_raw = str(entry.get("workspace_root", "")).strip()
    if not workspace_raw:
        return False
    workspace_root = Path(workspace_raw)
    try:
        _, _, running_map, _, _ = _load_progress(workspace_root)
    except Exception:
        return False
    task_ids = set(entry.get("task_ids") or [])
    for task_id, info in running_map.items():
        if gpu_id not in info.get("gpu_ids", []):
            continue
        if not task_ids or task_id in task_ids:
            return True
    return False


_LEASE_TTL_SEC = 3600  # 1 hour — if lease is older AND workspace can't confirm, remove


def _clean_global_gpu_leases_unlocked(leases: dict[str, dict]) -> dict[str, dict]:
    cleaned: dict[str, dict] = {}
    now = time.time()
    for gpu_key, entry in leases.items():
        try:
            gpu_id = int(gpu_key)
        except (TypeError, ValueError):
            continue
        # Fast path: if lease is recent, keep it without expensive workspace check
        claimed_at = entry.get("claimed_at", 0)
        if now - claimed_at < 60:  # Less than 1 minute old — always keep
            cleaned[str(gpu_id)] = entry
            continue
        # Check if workspace still confirms this lease
        if _lease_entry_matches_running(gpu_id, entry):
            cleaned[str(gpu_id)] = entry
        elif now - claimed_at < _LEASE_TTL_SEC:
            # Workspace doesn't confirm but lease is recent — keep (may be in transition)
            cleaned[str(gpu_id)] = entry
        # else: workspace doesn't confirm AND lease is old → drop
    return cleaned


def sync_workspace_gpu_leases(
    workspace_root: Path,
    running_map: dict[str, dict] | None = None,
) -> None:
    """Synchronize global GPU leases with a workspace's local running map."""
    workspace_root = Path(workspace_root).resolve()
    if running_map is None:
        _, _, running_map, _, _ = _load_progress(workspace_root)
    normalized_running = running_map if isinstance(running_map, dict) else {}
    workspace_key = str(workspace_root)
    project_name = workspace_root.parent.name if workspace_root.name == "current" else workspace_root.name

    with _global_gpu_leases_lock():
        leases = _clean_global_gpu_leases_unlocked(_load_global_gpu_leases_unlocked())
        leases = {
            gpu_key: entry
            for gpu_key, entry in leases.items()
            if entry.get("workspace_root") != workspace_key
        }
        for task_id, info in normalized_running.items():
            for gpu_id in info.get("gpu_ids", []):
                leases[str(gpu_id)] = {
                    "workspace_root": workspace_key,
                    "project_name": project_name,
                    "task_ids": [task_id],
                    "claimed_at": time.time(),
                }
        _save_global_gpu_leases_unlocked(leases)


def claim_next_batch(
    workspace_root: Path,
    candidate_gpu_ids: list[int],
    mode: str = "PILOT",
    *,
    gpus_per_task: int = 1,
    max_parallel_tasks: int | None = None,
) -> dict | None:
    """Atomically select and reserve the next batch of GPUs for a workspace."""
    workspace_root = Path(workspace_root).resolve()
    workspace_key = str(workspace_root)

    with _global_gpu_leases_lock():
        leases = _clean_global_gpu_leases_unlocked(_load_global_gpu_leases_unlocked())
        occupied_elsewhere = {
            int(gpu_key)
            for gpu_key, entry in leases.items()
            if entry.get("workspace_root") != workspace_key
        }
        available_gpu_ids = [
            gpu_id for gpu_id in candidate_gpu_ids
            if gpu_id not in occupied_elsewhere
        ]
        info = get_batch_info(
            workspace_root,
            available_gpu_ids,
            mode,
            gpus_per_task=gpus_per_task,
        )
        if info is None:
            _save_global_gpu_leases_unlocked(leases)
            return None

        batch = info["batch"]
        if max_parallel_tasks is not None:
            batch = batch[:max_parallel_tasks]
        info = dict(info)
        info["batch"] = batch
        info["candidate_gpu_ids"] = available_gpu_ids
        if not batch:
            _save_global_gpu_leases_unlocked(leases)
            return info

        project_name = workspace_root.parent.name if workspace_root.name == "current" else workspace_root.name
        claimed_at = time.time()
        for assignment in batch:
            for gpu_id in assignment["gpu_ids"]:
                leases[str(gpu_id)] = {
                    "workspace_root": workspace_key,
                    "project_name": project_name,
                    "task_ids": assignment["task_ids"],
                    "claimed_at": claimed_at,
                }
        _save_global_gpu_leases_unlocked(leases)
        return info


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

    # Sort by gpu_count ascending — small tasks first to maximize slot utilization
    sorted_tasks = sorted(ready_tasks, key=lambda t: t.get("gpu_count", default_gpus_per_task))

    available = list(gpu_ids)
    assignments = []

    for task in sorted_tasks:
        needed = task.get("gpu_count", default_gpus_per_task)
        needed = max(1, needed)  # at least 1 GPU

        if needed > len(available):
            continue  # Skip this task, try smaller ones

        assigned = available[:needed]
        available = available[needed:]
        assignments.append({
            "task_ids": [task["id"]],
            "gpu_ids": assigned,
        })

        if not available:
            break

    # Edge case: no task could be assigned (all tasks need more GPUs than available)
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


def _load_progress(workspace_root: Path) -> tuple[set, set, dict, dict, set]:
    """Load completed, running, failed, and timing info from gpu_progress.json.

    Returns (completed_ids, running_ids, running_map, timings, failed_ids).
    running_map: {task_id: {"gpu_ids": [...], "started_at": "..."}}
    """
    progress_path = workspace_root / "exp" / "gpu_progress.json"
    completed = set()
    running_map = {}
    timings = {}
    failed = set()
    if progress_path.exists():
        try:
            with open(progress_path, encoding="utf-8") as f:
                progress = json.load(f)
            completed = set(progress.get("completed", []))
            running_map = progress.get("running", {})
            timings = progress.get("timings", {})
            failed = set(progress.get("failed", []))
        except (json.JSONDecodeError, OSError):
            pass
    return completed, set(running_map.keys()), running_map, timings, failed


def register_running_tasks(workspace_root: Path, task_gpu_map: dict[str, list[int]]) -> None:
    """Register tasks as running in gpu_progress.json.

    Args:
        workspace_root: Path to workspace directory
        task_gpu_map: {task_id: [gpu_ids]} mapping of tasks to assigned GPUs
    """
    import datetime
    progress_path = workspace_root / "exp" / "gpu_progress.json"
    progress_path.parent.mkdir(parents=True, exist_ok=True)

    with _progress_lock(workspace_root):
        progress = {"completed": [], "failed": [], "running": {}, "timings": {}}
        if progress_path.exists():
            try:
                with open(progress_path, encoding="utf-8") as f:
                    progress.update(json.load(f))
            except (json.JSONDecodeError, OSError):
                pass

        if "running" not in progress:
            progress["running"] = {}
        progress.setdefault("failed", [])

        now = datetime.datetime.now().isoformat()
        for task_id, gpu_ids in task_gpu_map.items():
            if task_id in progress["failed"]:
                progress["failed"] = [item for item in progress["failed"] if item != task_id]
            progress["running"][task_id] = {
                "gpu_ids": gpu_ids,
                "started_at": now,
            }

        with open(progress_path, "w", encoding="utf-8") as f:
            json.dump(progress, f, indent=2)

        # Sync global leases INSIDE the lock so no one can modify progress between
        sync_workspace_gpu_leases(workspace_root, progress.get("running", {}))


def unregister_running_task(workspace_root: Path, task_id: str) -> None:
    """Remove a task from the running map in gpu_progress.json.

    Called when a task completes (the experimenter also adds it to 'completed').
    """
    progress_path = workspace_root / "exp" / "gpu_progress.json"
    if not progress_path.exists():
        return

    with _progress_lock(workspace_root):
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
            # Sync global leases INSIDE the lock to prevent race
            sync_workspace_gpu_leases(workspace_root, running)


def get_running_gpu_ids(workspace_root: Path) -> list[int]:
    """Get GPU IDs currently occupied by running tasks."""
    _, _, running_map, _, _ = _load_progress(workspace_root)
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

    # Load progress (completed + running + failed)
    completed, running_ids, _, _, failed = _load_progress(workspace_root)

    # Filter out completed, running, AND failed tasks
    excluded = completed | running_ids | failed
    remaining = [t for t in tasks if t["id"] not in excluded]
    if not remaining:
        # Check if there are running tasks (not truly done yet)
        if running_ids:
            return []  # Still running, nothing new to schedule
        return None  # All done

    # Treat failed as resolved for dependency purposes (don't block downstream)
    resolved = completed | failed
    ready = [
        t for t in remaining
        if all(dep in resolved for dep in t.get("depends_on", []))
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

    # Load progress (completed + running + failed)
    completed, running_ids, _, timings, failed = _load_progress(workspace_root)

    # Filter out completed, running, AND failed tasks
    excluded = completed | running_ids | failed
    remaining = [t for t in tasks if t["id"] not in excluded]
    if not remaining:
        if running_ids:
            return {"batch": [], "estimated_minutes": 0,
                    "remaining_count": len(running_ids),
                    "completed_count": len(completed),
                    "total_count": len(tasks)}
        return None

    # Treat failed tasks as "resolved" for dependency purposes (don't block downstream)
    resolved = completed | failed
    ready = [
        t for t in remaining
        if all(dep in resolved for dep in t.get("depends_on", []))
    ]

    if not ready:
        return {"batch": [], "estimated_minutes": 0,
                "remaining_count": len(remaining) + len(running_ids),
                "completed_count": len(completed),
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
        "remaining_count": len(remaining) + len(running_ids),  # pending + running
        "completed_count": len(completed),
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


def parse_gpu_snapshot(nvidia_smi_output: str) -> list[dict]:
    """Parse nvidia-smi CSV output into structured per-GPU memory snapshots."""
    snapshot: list[dict] = []
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
        except (TypeError, ValueError, IndexError):
            continue

        entry = {
            "gpu_id": gpu_id,
            "memory_used_mb": mem_used,
        }
        if len(parts) >= 3:
            try:
                mem_total = int(float(parts[2]))
            except (TypeError, ValueError, IndexError):
                mem_total = 0
            if mem_total > 0:
                entry["memory_total_mb"] = mem_total
                entry["memory_used_pct"] = round((mem_used / mem_total) * 100.0, 2)
        snapshot.append(entry)
    return snapshot


def write_poll_result(
    marker_file: str,
    *,
    free_gpus: list[int],
    poll_count: int = 0,
    snapshot: list[dict] | None = None,
    source: str = "",
) -> dict:
    """Persist free GPU polling results for schedulers and supervisors."""
    path = Path(marker_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "free_gpus": list(free_gpus),
        "poll_count": poll_count,
        "snapshot": list(snapshot or []),
        "source": source,
        "updated_at": time.time(),
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)
    return payload


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
    *,
    workspace_path: str = "",
    heartbeat_polls: int = 3,
    task_gpu_map: dict[str, list[int]] | None = None,
) -> str:
    """Generate a bash script that monitors running experiments via SSH.

    The script:
    1. Checks DONE/PID status via batched SSH (single connection per poll)
    2. Refreshes GPU state via nvidia-smi (zero LLM token cost)
    3. Calls cli_dispatch_tasks when tasks complete
    4. Detects stuck processes (dead PID without DONE marker)
    5. Writes wake events to the supervisor wake queue
    6. Exits when all monitored tasks have DONE markers or on timeout

    This replaces the Opus experiment-supervisor subagent with a pure bash
    daemon — zero LLM tokens consumed for routine monitoring.

    Args:
        ssh_server: SSH host to connect to
        remote_project_dir: Remote project directory
        task_ids: List of task IDs to monitor
        poll_interval_sec: Seconds between checks (default 300 = 5 min)
        timeout_minutes: Maximum monitoring time; 0 = unlimited
        marker_file: Local path to write monitoring status JSON
        notify_cmd: Optional shell command to run on completion
        workspace_path: Local workspace root (for GPU refresh + dispatch)
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

    # GPU refresh and dispatch blocks (only when workspace_path is provided)
    gpu_refresh_block = ""
    dispatch_block = ""
    wake_queue_block = ""
    stuck_detection_block = ""
    final_sync_block = ""

    if workspace_path:
        from sibyl._paths import REPO_ROOT

        repo_root = str(REPO_ROOT)
        python_exe = f"{repo_root}/.venv/bin/python3"

        # Wake queue path — matches runtime_cli._EXPERIMENT_MAIN_WAKE_QUEUE
        wake_queue = f"{workspace_path}/exp/experiment_supervisor_main_wake.jsonl"
        # Also check iteration-dirs active workspace
        wake_queue_alt = f"{workspace_path}/current/exp/experiment_supervisor_main_wake.jsonl"

        wake_queue_block = f'''
# Helper: enqueue a wake event for the main system
_enqueue_wake() {{
    local kind="$1" summary="$2" urgency="${{3:-high}}" requires_main="${{4:-false}}"
    local ts=$(date +%s%3N)
    local queue="{wake_queue}"
    [ -f "{wake_queue_alt}" ] && queue="{wake_queue_alt}"
    mkdir -p "$(dirname "$queue")"
    printf '%s\\n' "{{\\"event_id\\":\\"wake-${{ts}}-monitor\\",\\"owner_id\\":\\"monitor_daemon_$$\\",\\"kind\\":\\"$kind\\",\\"summary\\":\\"$summary\\",\\"urgency\\":\\"$urgency\\",\\"requires_main_system\\":$requires_main,\\"created_at\\":$ts}}" \\
        >> "$queue"
}}
'''

        # Build task_gpu_map JSON for digest analysis
        _task_gpu_json = json.dumps(task_gpu_map or {})

        # Adaptive heartbeat: based on estimated remaining time
        # <30min→every 3 polls, 30-120min→every 5 polls, >120min→every 6 polls
        heartbeat_interval = heartbeat_polls

        gpu_refresh_block = f'''
    # ── GPU State Refresh (every poll — needed for real-time free GPU detection) ──
    GPU_OUTPUT=$(ssh {ssh_server} "nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits" 2>/dev/null)
    if [ $? -eq 0 ] && [ -n "$GPU_OUTPUT" ]; then
        cd "{repo_root}" && "{python_exe}" -m sibyl.cli record-gpu-poll \\
            "{workspace_path}" --nvidia-smi-output "$GPU_OUTPUT" \\
            --source "monitor_daemon" > /dev/null 2>&1

        # ── GPU Efficiency Digest (every {heartbeat_interval} polls) ──
        if [ $((i % {heartbeat_interval})) -eq 0 ]; then
            DIGEST=$("{python_exe}" -c "
import json, sys
from sibyl.experiment_digest import analyze_gpu_efficiency, format_digest_for_llm, build_digest
gpu_out = sys.argv[1]
task_gpus = json.loads(sys.argv[2])
progress = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {{}}
analysis = analyze_gpu_efficiency(gpu_out, running_task_gpus=task_gpus)
digest = build_digest(analysis, [], analysis.get('recommendations', []), task_progress=progress, elapsed_min=int(sys.argv[4]) if len(sys.argv) > 4 else 0)
print(json.dumps(digest))
" "$GPU_OUTPUT" {shlex.quote(_task_gpu_json)} "${{PROGRESS_JSON:-{{}}}}" "$(((${{elapsed:-0}}) / 60))" 2>/dev/null)

            if [ -n "$DIGEST" ]; then
                # Check for free GPUs in digest → proactive dispatch
                FREE_COUNT=$(echo "$DIGEST" | "{python_exe}" -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('gpu_analysis',{{}}).get('free_gpus',[])))" 2>/dev/null || echo "0")
                if [ "$FREE_COUNT" -gt 0 ] && [ "$DISPATCH" != "true" ]; then
                    DISPATCH_RESULT=$(cd "{repo_root}" && "{python_exe}" -m sibyl.cli dispatch "{workspace_path}" 2>/dev/null)
                    PROACTIVE_COUNT=$(echo "$DISPATCH_RESULT" | "{python_exe}" -c \\
                        "import json,sys; d=json.load(sys.stdin); print(len(d.get('dispatch',[])))" 2>/dev/null || echo "0")
                    if [ "$PROACTIVE_COUNT" -gt 0 ]; then
                        _enqueue_wake "dispatch_ready" "$PROACTIVE_COUNT tasks dispatched to free GPUs" "high" "true"
                    fi
                fi

                # Check for underutilized GPUs → notify main system
                UNDERUTIL_COUNT=$(echo "$DIGEST" | "{python_exe}" -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('gpu_analysis',{{}}).get('underutilized',[])))" 2>/dev/null || echo "0")
                if [ "$UNDERUTIL_COUNT" -gt 0 ]; then
                    _enqueue_wake "gpu_underutilized" "$UNDERUTIL_COUNT GPUs underutilized" "medium" "false"
                fi

                # Periodic review with full digest
                _enqueue_wake "periodic_review" "Digest available" "low" "false"
            fi
        fi
    fi

    # ── Append to monitor history ──
    echo "{{\\"ts\\": $(date +%s), \\"poll\\": $i, \\"done_count\\": $done_count, \\"total\\": $TOTAL}}" >> "{workspace_path}/exp/monitor_history.jsonl" 2>/dev/null
'''

        dispatch_block = f'''
    # ── Dynamic Dispatch (when new tasks completed) ──
    if [ "$DISPATCH" = "true" ]; then
        # Sync completed tasks to experiment_state.json before dispatching
        if [ -n "$COMPLETED_JSON" ]; then
            cd "{repo_root}" && "{python_exe}" -m sibyl.cli sync-experiment-completions \\
                "{workspace_path}" --completed-json "[$COMPLETED_JSON]" > /dev/null 2>&1
        fi
        DISPATCH_RESULT=$(cd "{repo_root}" && "{python_exe}" -m sibyl.cli dispatch "{workspace_path}" 2>/dev/null)
        DISPATCH_COUNT=$(echo "$DISPATCH_RESULT" | "{python_exe}" -c \\
            "import json,sys; d=json.load(sys.stdin); print(len(d.get('dispatch',[])))" 2>/dev/null || echo "0")
        if [ "$DISPATCH_COUNT" -gt 0 ]; then
            _enqueue_wake "dispatch_ready" "$DISPATCH_COUNT new tasks dispatched" "high" "true"
        fi
    fi
'''

        final_sync_block = f'''
        # Final sync: mark all tasks completed in experiment_state.json
        if [ -n "$COMPLETED_JSON" ]; then
            cd "{repo_root}" && "{python_exe}" -m sibyl.cli sync-experiment-completions \\
                "{workspace_path}" --completed-json "[$COMPLETED_JSON]" > /dev/null 2>&1
        fi'''

        stuck_detection_block = f'''
    # ── Stuck Process Detection ──
    STUCK_TASKS=""
    for task_id in "${{ALL_TASKS[@]}}"; do
        # Skip completed tasks
        echo ",$COMPLETED," | grep -q ",$task_id," && continue

        # Check if PID is dead but no DONE marker
        pid_status=$(ssh {ssh_server} "
            pid=\\$(cat {remote_project_dir}/exp/results/${{task_id}}.pid 2>/dev/null)
            if [ -n \\"\\$pid\\" ]; then
                if kill -0 \\$pid 2>/dev/null; then
                    echo ALIVE
                else
                    echo DEAD
                fi
            else
                echo NO_PID
            fi
        " 2>/dev/null)
        if [ "$pid_status" = "DEAD" ]; then
            if [ -z "$STUCK_TASKS" ]; then
                STUCK_TASKS="$task_id"
            else
                STUCK_TASKS="$STUCK_TASKS,$task_id"
            fi
        fi
    done
    if [ -n "$STUCK_TASKS" ]; then
        _enqueue_wake "task_died" "Process dead without DONE marker: $STUCK_TASKS" "high" "true"
    fi
'''

    return f'''#!/bin/bash
# Sibyl Experiment Monitor Daemon
# Tasks: {task_ids_str} on {ssh_server}
# Poll every {poll_interval_sec}s, timeout: {"unlimited" if timeout_minutes == 0 else f"{timeout_minutes}min"}
# Replaces Opus experiment-supervisor — zero LLM tokens consumed.

MARKER="{marker_file}"
REMOTE_DIR="{remote_project_dir}"
ALL_TASKS=({task_ids_str})
TOTAL={task_count}
start_time=$(date +%s)
PREV_DONE_COUNT=0
{wake_queue_block}
echo '{{"status": "monitoring", "total": {task_count}, "completed": [], "pending": {json.dumps(task_ids)}, "dispatch_needed": false}}' > "$MARKER"

i=0
while true; do
    i=$((i + 1))
    COMPLETED=""
    COMPLETED_JSON=""
    PENDING=""
    PENDING_JSON=""
    done_count=0

    # ── Batched DONE + PID check (single SSH connection) ──
    BATCH_RESULT=$(ssh {ssh_server} "
        for t in {task_ids_str}; do
            if test -f $REMOTE_DIR/exp/results/${{t}}_DONE; then
                echo \\"\\$t:DONE\\"
            else
                echo \\"\\$t:PENDING\\"
            fi
        done
    " 2>/dev/null)

    while IFS= read -r line; do
        task_id=$(echo "$line" | cut -d: -f1)
        status=$(echo "$line" | cut -d: -f2)
        [ -z "$task_id" ] && continue
        if [ "$status" = "DONE" ]; then
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
                PENDING="$PENDING $task_id"
                PENDING_JSON="$PENDING_JSON, \\"$task_id\\""
            fi
        fi
    done <<< "$BATCH_RESULT"

    # Detect newly completed tasks
    DISPATCH="false"
    if [ "$done_count" -gt "$PREV_DONE_COUNT" ]; then
        DISPATCH="true"
    fi
    PREV_DONE_COUNT=$done_count

    # ── Collect PROGRESS snapshots (single SSH) ──
    PROGRESS_JSON=""
    if [ -n "$PENDING" ]; then
        PROG_RESULT=$(ssh {ssh_server} "
            for t in $PENDING; do
                prog=\\$(cat $REMOTE_DIR/exp/results/${{t}}_PROGRESS.json 2>/dev/null)
                [ -n \\"\\$prog\\" ] && echo \\"${{t}}:\\$prog\\"
            done
        " 2>/dev/null)

        while IFS= read -r line; do
            [ -z "$line" ] && continue
            tid=$(echo "$line" | cut -d: -f1)
            prog=$(echo "$line" | cut -d: -f2-)
            if [ -n "$prog" ]; then
                entry="\\"$tid\\": $prog"
                if [ -z "$PROGRESS_JSON" ]; then
                    PROGRESS_JSON="$entry"
                else
                    PROGRESS_JSON="$PROGRESS_JSON, $entry"
                fi
            fi
        done <<< "$PROG_RESULT"
    fi

    elapsed=$(( $(date +%s) - start_time ))
    echo "[monitor $i] $done_count/$TOTAL done (elapsed: ${{elapsed}}s)"
{gpu_refresh_block}{dispatch_block}{stuck_detection_block}
    # ── Write marker file ──
    if [ "$done_count" -eq "$TOTAL" ]; then{final_sync_block}
        echo '{{"status": "all_complete", "completed": ['$COMPLETED_JSON'], "pending": [], "dispatch_needed": false, "progress": {{'$PROGRESS_JSON'}}, "elapsed_sec": '$elapsed', "poll_count": '$i'}}' > "$MARKER"
        echo "[monitor] All {task_count} tasks complete!"{notify_block}
        [ -n "$(type -t _enqueue_wake 2>/dev/null)" ] && _enqueue_wake "all_complete" "All {task_count} tasks finished" "high" "true"
        exit 0
    fi

    echo '{{"status": "monitoring", "completed": ['$COMPLETED_JSON'], "pending": ['$PENDING_JSON'], "dispatch_needed": '$DISPATCH', "progress": {{'$PROGRESS_JSON'}}, "elapsed_sec": '$elapsed', "poll_count": '$i'}}' > "$MARKER"
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
