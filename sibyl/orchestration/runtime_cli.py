"""Runtime-oriented CLI helpers extracted from the legacy orchestrator."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from sibyl.event_logger import EventLogger

from .workspace_paths import (
    project_marker_file,
    resolve_active_workspace_path,
    resolve_workspace_root,
)


def cli_experiment_status(workspace_path: str = "") -> None:
    """Check experiment status with rich progress information."""
    import datetime as dt

    from sibyl.experiment_recovery import load_experiment_state
    from sibyl.gpu_scheduler import _load_progress, read_monitor_result

    if not workspace_path:
        result = {
            "status": "workspace_required",
            "error": "workspace_path is required for multi-project isolated experiment status",
        }
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    project_root = resolve_workspace_root(workspace_path)
    active_root = resolve_active_workspace_path(workspace_path)
    monitor = read_monitor_result(project_marker_file(project_root, "exp_monitor"))
    result = dict(monitor) if monitor else {"status": "no_monitor"}
    completed, running_ids, running_map, timings = _load_progress(active_root)

    task_plan_path = active_root / "plan" / "task_plan.json"
    total_tasks = 0
    task_names: dict[str, str] = {}
    task_estimates: dict[str, int] = {}
    if task_plan_path.exists():
        try:
            plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
            for task in plan.get("tasks", []):
                total_tasks += 1
                task_names[task["id"]] = task.get("name", task["id"])
                task_estimates[task["id"]] = task.get("estimated_minutes", 0)
        except (json.JSONDecodeError, OSError):
            pass

    pending_count = max(0, total_tasks - len(completed) - len(running_ids))
    elapsed_sec = result.get("elapsed_sec", 0)
    elapsed_min = elapsed_sec // 60 if elapsed_sec else 0

    max_remaining_sec = 0
    task_lines = []
    for task_id, info in running_map.items():
        gpu_ids = info.get("gpu_ids", [])
        name = task_names.get(task_id, task_id)
        started_at = info.get("started_at", "")
        task_elapsed_min = 0
        if started_at:
            try:
                start_dt = dt.datetime.fromisoformat(started_at)
                task_elapsed_min = int((dt.datetime.now() - start_dt).total_seconds() / 60)
            except (ValueError, TypeError):
                pass
        estimate = task_estimates.get(task_id, 0)
        if estimate > 0:
            remaining = max(0, estimate * 60 - task_elapsed_min * 60)
            max_remaining_sec = max(max_remaining_sec, remaining)

        gpu_str = ",".join(str(gpu_id) for gpu_id in gpu_ids)
        task_lines.append(f"    {name} -> GPU[{gpu_str}] ({task_elapsed_min}min)")

    est_remaining_min = int(max_remaining_sec / 60)

    exp_state = load_experiment_state(active_root)
    task_progress = {}
    for task_id, task in exp_state.tasks.items():
        if task.get("progress"):
            task_progress[task_id] = task["progress"]
    result["task_progress"] = task_progress
    if exp_state.last_recovery_at:
        result["last_recovery_at"] = exp_state.last_recovery_at

    lines = [
        "",
        "+-----------------------------------------+",
        "|      SIBYL - Experiment Monitor          |",
        "+-----------------------------------------+",
    ]

    if total_tasks > 0:
        done_pct = len(completed) / total_tasks
        bar_w = 20
        filled = int(bar_w * done_pct)
        bar = "#" * filled + "." * (bar_w - filled)
        pct_str = f"{int(done_pct * 100)}%"
        lines.append(f"|  [{bar}] {len(completed)}/{total_tasks} ({pct_str})")

    status_label = {
        "all_complete": "ALL DONE",
        "monitoring": "RUNNING",
        "timeout": "TIMEOUT",
        "no_monitor": "INITIALIZING",
    }.get(result["status"], result["status"])
    lines.append(f"|  Status: {status_label}")

    if task_lines:
        lines.append("|  Running:")
        for task_line in task_lines:
            lines.append(f"|  {task_line}")

    if pending_count > 0:
        lines.append(f"|  Queued: {pending_count} tasks waiting")

    time_parts = []
    if elapsed_min > 0:
        time_parts.append(f"elapsed {elapsed_min}min")
    if est_remaining_min > 0:
        time_parts.append(f"~{est_remaining_min}min remaining")
    if time_parts:
        lines.append(f"|  Time: {', '.join(time_parts)}")

    lines.append("|")
    lines.append("|  System running, please wait...")
    lines.append("+-----------------------------------------+")
    lines.append("")

    result["display"] = "\n".join(lines)
    result["completed_count"] = len(completed)
    result["running_count"] = len(running_ids)
    result["pending_count"] = pending_count
    result["total_tasks"] = total_tasks
    result["elapsed_min"] = elapsed_min
    result["estimated_remaining_min"] = est_remaining_min

    print(json.dumps(result, indent=2, ensure_ascii=False))

    try:
        monitor_persist = {key: value for key, value in result.items() if key != "display"}
        monitor_persist["snapshot_at"] = time.time()
        persist_path = active_root / "exp" / "monitor_status.json"
        persist_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = persist_path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(monitor_persist, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(persist_path)
    except Exception:
        pass


def cli_dispatch_tasks(
    workspace_path: str,
    *,
    orchestrator_factory: Callable[[str], Any],
    skill_builder: Callable[[Any, str, str, list[int], str], dict],
) -> None:
    """Dynamic dispatch: find free GPUs and return next task assignments."""
    from sibyl.experiment_recovery import register_dispatched_tasks
    from sibyl.gpu_scheduler import claim_next_batch, get_running_gpu_ids, read_poll_result

    orchestrator = orchestrator_factory(workspace_path)
    status = orchestrator.ws.get_status()
    stage = status.stage
    if stage not in ("pilot_experiments", "experiment_cycle"):
        print(json.dumps({"dispatch": [], "reason": "not_experiment_stage"}))
        return

    mode = "PILOT" if stage == "pilot_experiments" else "FULL"
    active_root = orchestrator.ws.active_root
    active_workspace = str(active_root)

    if orchestrator.config.gpu_poll_enabled:
        polled = read_poll_result(project_marker_file(orchestrator.ws.root, "gpu_free"))
        if not polled:
            print(json.dumps({"dispatch": [], "reason": "awaiting_gpu_poll"}))
            return
        all_gpu_ids = polled[:orchestrator.config.max_gpus]
    else:
        all_gpu_ids = list(range(orchestrator.config.max_gpus))

    occupied = set(get_running_gpu_ids(active_root))
    free_gpus = [gpu_id for gpu_id in all_gpu_ids if gpu_id not in occupied]
    if not free_gpus:
        print(json.dumps({"dispatch": [], "reason": "no_free_gpus"}))
        return

    info = claim_next_batch(
        active_root,
        free_gpus,
        mode,
        gpus_per_task=orchestrator.config.gpus_per_task,
        max_parallel_tasks=orchestrator.config.max_parallel_tasks,
    )
    if info is None:
        print(json.dumps({"dispatch": [], "reason": "all_done"}))
        return

    batch = info["batch"]
    if not batch:
        print(json.dumps({"dispatch": [], "reason": "no_ready_tasks"}))
        return

    task_gpu_map = {}
    for assignment in batch:
        for task_id in assignment["task_ids"]:
            task_gpu_map[task_id] = assignment["gpu_ids"]
    remote_project_dir = f"{orchestrator.config.remote_base}/projects/{orchestrator.ws.name}"
    register_dispatched_tasks(active_root, task_gpu_map, remote_project_dir)

    skills = []
    for assignment in batch:
        task_ids = ",".join(assignment["task_ids"])
        gpu_ids = assignment["gpu_ids"]
        skills.append(skill_builder(orchestrator, mode, active_workspace, gpu_ids, task_ids))

    gpu_summary = ", ".join(
        f"{assignment['task_ids'][0]}→GPU{assignment['gpu_ids']}"
        for assignment in batch
    )
    print(json.dumps({
        "dispatch": batch,
        "skills": skills,
        "description": f"动态调度: {gpu_summary}",
        "estimated_minutes": info["estimated_minutes"],
    }, indent=2))

    try:
        all_task_ids = [task_id for assignment in batch for task_id in assignment["task_ids"]]
        all_gpu_ids_used = [gpu_id for assignment in batch for gpu_id in assignment["gpu_ids"]]
        EventLogger(Path(workspace_path)).task_dispatch(
            task_ids=all_task_ids,
            gpu_ids=all_gpu_ids_used,
            iteration=status.iteration,
        )
    except Exception:
        pass


def cli_recover_experiments(
    workspace_path: str,
    *,
    orchestrator_factory: Callable[[str], Any],
) -> None:
    """Detect and prepare recovery for interrupted experiments."""
    from sibyl.experiment_recovery import (
        generate_detection_script,
        get_running_tasks,
        load_experiment_state,
        migrate_from_gpu_progress,
        save_experiment_state,
    )

    active_root = resolve_active_workspace_path(workspace_path)
    state = load_experiment_state(active_root)
    if not state.tasks:
        state = migrate_from_gpu_progress(active_root)
        if state.tasks:
            save_experiment_state(active_root, state)

    running = get_running_tasks(state)
    if not running:
        print(json.dumps({
            "status": "no_recovery_needed",
            "total_tasks": len(state.tasks),
        }, indent=2))
        return

    orchestrator = orchestrator_factory(workspace_path)
    remote_project_dir = f"{orchestrator.config.remote_base}/projects/{orchestrator.ws.name}"
    script = generate_detection_script(remote_project_dir, running)
    print(json.dumps({
        "status": "has_running_tasks",
        "running_tasks": running,
        "detection_script": script,
        "ssh_server": orchestrator.config.ssh_server,
        "instructions": (
            "Run the detection_script on the remote server via SSH, "
            "then pass the output to cli_apply_recovery."
        ),
    }, indent=2))


def cli_apply_recovery(workspace_path: str, ssh_output: str) -> None:
    """Apply recovery based on SSH detection output."""
    from sibyl.experiment_recovery import (
        load_experiment_state,
        parse_detection_output,
        recover_from_detection,
        save_experiment_state,
        sync_to_gpu_progress,
    )

    active_root = resolve_active_workspace_path(workspace_path)
    state = load_experiment_state(active_root)
    detection = parse_detection_output(ssh_output)
    result = recover_from_detection(state, detection)

    save_experiment_state(active_root, state)
    sync_to_gpu_progress(active_root, state)

    output = asdict(result)
    output["status"] = "recovered"
    print(json.dumps(output, indent=2))
